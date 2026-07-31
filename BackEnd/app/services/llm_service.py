import asyncio
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from app.core.config import settings
from app.prompts import SYSTEM_PROMPT

# 로컬 llama-cpp는 단일 스레드 실행(GPU 직렬) → worker 1.
# Vertex는 네트워크 호출이라 병렬 가능 → worker 여러 개(동시성 확보).
# [확장 지점] 다중 유저 동시 답변이 필요하면(예: 5090 32GB 도입) 여기 worker를 늘리는 대신
#   provider="vllm"을 추가해 continuous batching 엔진(vLLM/TGI)으로 교체하는 게 정석이다.
#   _generate에 분기 한 줄 + _generate_vllm() 추가면 되고, 라우팅·검색 로직은 그대로다.
#   그때 chat_service의 세션별 prev_context 정합성(동시 요청 race)도 함께 검토한다.
_local_executor = ThreadPoolExecutor(max_workers=1)
_vertex_executor = ThreadPoolExecutor(max_workers=8)


class LlmService:
    """답변 생성 LLM. settings.LLM_PROVIDER 로 local(Bllossom) ↔ vertex(Gemini) 전환."""

    def __init__(self):
        self.provider = (settings.LLM_PROVIDER or "local").lower()
        self.model = None            # 로컬 Llama
        self.vertex_client = None    # Vertex genai client

    # ── 로딩 ──────────────────────────────────────────────────
    def load_model(self):
        if settings.DEV_MODE:
            print("DEV_MODE: LLM 로딩 스킵")
            return
        if self.provider == "vertex":
            self._init_vertex()
        else:
            self._load_local()

    def _load_local(self):
        # Windows: llama-cpp가 CUDA DLL을 찾을 수 있도록 torch lib 경로 추가
        if sys.platform == "win32":
            import torch as _torch
            os.add_dll_directory(os.path.join(os.path.dirname(_torch.__file__), "lib"))
        from llama_cpp import Llama
        print(f"모델 로딩 중: {settings.MODEL_PATH}")
        self.model = Llama(
            model_path=settings.MODEL_PATH,
            n_gpu_layers=settings.LLM_GPU_LAYERS,   # env로 조정(3070=25 / 5090=-1 전체)
            n_ctx=settings.LLM_N_CTX,               # env로 조정(VRAM 늘면 8192 등)
            n_batch=128,
            verbose=False,
        )
        print("모델 로딩 완료! (로컬 Bllossom, llama-cpp-python)")

    def _init_vertex(self):
        from google import genai
        # API 키가 있으면 Vertex Express 모드(vertexai=True + api_key), 없으면 서비스계정(Vertex AI)
        # ★ vertexai=True 필수 — 없으면 AI Studio(generativelanguage) 경로로 새서 데이터가
        #   학습에 쓰이고 403 API_KEY_SERVICE_BLOCKED가 남. True면 같은 키라도 Vertex 경로로 감.
        #   Express 모드는 project/location 불필요(api_key가 라우팅). 콘솔 생성 코드와 동일.
        if settings.GEMINI_API_KEY:
            self.vertex_client = genai.Client(vertexai=True, api_key=settings.GEMINI_API_KEY)
            print(f"[LLM] Vertex Gemini(Express·API키) 준비 완료: {settings.GEMINI_MODEL}")
        else:
            if settings.GOOGLE_APPLICATION_CREDENTIALS:
                os.environ.setdefault(
                    "GOOGLE_APPLICATION_CREDENTIALS", settings.GOOGLE_APPLICATION_CREDENTIALS
                )
            self.vertex_client = genai.Client(
                vertexai=True,
                project=settings.GCP_PROJECT_ID,
                location=settings.GCP_LOCATION,
            )
            print(f"[LLM] Vertex Gemini(서비스계정) 준비 완료: {settings.GEMINI_MODEL} @ {settings.GCP_LOCATION}")

    # ── 컨텍스트 예산 맞추기 ──────────────────────────────────────
    def fit_context(self, context: str, overhead_text: str,
                    min_answer_tokens: int = 800, reserve: int = 64) -> str:
        """답변 생성에 min_answer_tokens가 남도록 context를 줄인다(문서 단위로 뒤부터 제외).

        n_ctx(4096)는 프롬프트+답변의 '합계'라, 컨텍스트가 길면 답변이 잘린다. 예산을
        고정 상수(MAX_TOTAL_CONTEXT)로 잡으면 프롬프트 규칙 크기(RAG 골격만 946토큰)를 반영
        못 해 어떤 질문은 답변이 61토큰까지 쪼그라들었다. 여기서 '실제 오버헤드'를 토큰으로
        재서 컨텍스트 상한을 역산한다 — 짧은 프롬프트엔 컨텍스트를 넉넉히, 규칙이 무거운
        프롬프트엔 알아서 조인다(유동적).

        overhead_text: 컨텍스트를 뺀 프롬프트 전체 + system_prompt (실측 대상).
        로컬 모델이 아닐 때(vertex는 컨텍스트가 훨씬 큼, DEV_MODE는 모델 없음)는 그대로 반환.
        """
        if self.provider == "vertex" or self.model is None or not context:
            return context
        n_ctx = self.model.n_ctx()
        overhead = len(self.model.tokenize(overhead_text.encode("utf-8")))
        budget = n_ctx - overhead - min_answer_tokens - reserve
        if budget <= 0:
            # 규칙+질문만으로 예산을 다 먹은 극단 케이스. 답변 몫을 지키려 컨텍스트를 최소로.
            budget = max(200, n_ctx - overhead - self._MIN_ANSWER_TOKENS - reserve)
        ctx_toks = self.model.tokenize(context.encode("utf-8"))
        if len(ctx_toks) <= budget:
            return context

        # 1) 문서 단위로 '뒤에서부터' 통째 제외.
        # 문자열 중간을 자르면 리트리버가 병합할 때 뒤에 붙인 '정답 앵커'
        # (_merge_same_article의 앵커 예외 — 문서 뒤쪽 청크가 정답인 경우)가 가장 먼저
        # 날아간다. 실측 사례: '학사경고 기준'의 정의는 성적평가 문서 뒤쪽 청크에 있다.
        # 컨텍스트는 '[source=…]' 헤더로 문서가 구분되고 점수 내림차순이라, 뒤 문서일수록
        # 관련도가 낮다 → 뒤부터 버리는 게 정답을 지키면서 예산을 맞추는 방법이다.
        parts = context.split("\n\n[source=")
        if len(parts) > 1:
            parts = [parts[0]] + [f"[source={p}" for p in parts[1:]]
            while len(parts) > 1:
                parts.pop()
                cand = "\n\n".join(parts)
                if len(self.model.tokenize(cand.encode("utf-8"))) <= budget:
                    print(f"[LLM] 컨텍스트 예산 절단(문서 단위): {len(context)}자 → {len(cand)}자 "
                          f"(오버헤드 {overhead}토큰, 답변보장 {min_answer_tokens}토큰)")
                    return cand

        # 2) 단일 문서만으로 예산을 넘는 경우에만 최후수단으로 토큰 절단
        #    (줄 경계로 정리해 문장 중간 절단 방지)
        cut = self.model.detokenize(ctx_toks[:budget]).decode("utf-8", errors="ignore")
        trimmed = cut.rsplit("\n", 1)[0] if "\n" in cut else cut
        print(f"[LLM] 컨텍스트 예산 절단: {len(context)}자 → {len(trimmed)}자 "
              f"(오버헤드 {overhead}토큰, 답변보장 {min_answer_tokens}토큰)")
        return trimmed

    # ── 생성 ──────────────────────────────────────────────────
    def _generate(self, question: str, max_tokens: int = 512,
                  system_prompt: str = SYSTEM_PROMPT, temperature: float = 0.3) -> str:
        if settings.DEV_MODE:
            return f"[DEV_MODE] 질문 수신: {question}"
        if self.provider == "vertex":
            return self._generate_vertex(question, max_tokens, system_prompt, temperature)
        return self._generate_local(question, max_tokens, system_prompt, temperature)

    # 답변 생성에 최소한 확보돼야 하는 토큰. 이보다 여유가 없으면 프롬프트가 과대한 것이다.
    _MIN_ANSWER_TOKENS = 128

    def _generate_local(self, question, max_tokens, system_prompt, temperature) -> str:
        try:
            t0 = time.time()
            # n_ctx(4096)는 프롬프트와 생성의 '합계'다. RAG 컨텍스트가 길면 요청한 max_tokens를
            # 다 쓸 수 없으므로 남는 만큼으로 줄인다. 이 클램프가 있어야 호출부가 넉넉히
            # 요청해도(짧은 컨텍스트일 때 긴 답변을 받으려고) 컨텍스트 초과로 깨지지 않는다.
            n_ctx = self.model.n_ctx()
            used = len(self.model.tokenize(f"{system_prompt}\n{question}".encode("utf-8")))
            room = n_ctx - used - 64                                # 64 = 채팅 템플릿 마커 여유
            if room < self._MIN_ANSWER_TOKENS:
                # 프롬프트만으로 컨텍스트를 거의 다 먹은 상태. 예전엔 max(128, ...) 하한 때문에
                # 초과가 강제되어 llama.cpp가 ValueError를 던졌고 요청이 500으로 죽었다.
                # 여기서 프롬프트를 자르면 규칙('문서에 없는 내용은 추측하지 않는다')이나 질문이
                # 날아가 근거 없는 답이 나올 수 있으므로, 조용히 망가뜨리지 않고 명시적으로 알린다.
                raise ValueError(
                    f"프롬프트가 컨텍스트 창을 초과합니다 ({used}토큰 / n_ctx {n_ctx}). "
                    f"MAX_TOTAL_CONTEXT를 줄이세요."
                )
            capped = min(max_tokens, room)
            if capped < max_tokens:
                print(f"[LLM] max_tokens {max_tokens} → {capped} (프롬프트 {used}토큰 / n_ctx {n_ctx})")
            print("[LLM] 로컬 추론 시작")
            response = self.model.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
                max_tokens=capped,
                temperature=temperature,
                top_p=0.9,
                repeat_penalty=1.1,
            )
            result = response["choices"][0]["message"]["content"]
            usage = response.get("usage", {})
            print(f"[LLM] 생성 완료 | 출력 토큰: {usage.get('completion_tokens', '?')} | {time.time()-t0:.1f}s")
            return result
        except Exception as e:
            print(f"[LLM] 로컬 추론 오류: {type(e).__name__}: {e}")
            raise

    def _generate_vertex(self, question, max_tokens, system_prompt, temperature) -> str:
        from google.genai import types
        try:
            t0 = time.time()
            print("[LLM] Vertex Gemini 추론 시작")
            resp = self.vertex_client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=question,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                ),
            )
            result = (resp.text or "").strip()
            print(f"[LLM] Vertex 생성 완료 | {time.time()-t0:.1f}s")
            return result
        except Exception as e:
            print(f"[LLM] Vertex 추론 오류: {type(e).__name__}: {e}")
            raise

    # ── 비동기 인터페이스 (호출부 변경 없음) ──────────────────
    async def answer(self, question: str, max_tokens: int = 512,
                     system_prompt: str = SYSTEM_PROMPT, temperature: float = 0.3) -> str:
        loop = asyncio.get_event_loop()
        executor = _vertex_executor if self.provider == "vertex" else _local_executor
        return await loop.run_in_executor(
            executor, self._generate, question, max_tokens, system_prompt, temperature
        )


llm_service = LlmService()
