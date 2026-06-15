import asyncio
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

# Windows: llama-cpp-python이 CUDA DLL을 찾을 수 있도록 torch lib 경로 추가
if sys.platform == "win32":
    import torch as _torch
    os.add_dll_directory(os.path.join(os.path.dirname(_torch.__file__), "lib"))

from llama_cpp import Llama
from app.core.config import settings

SYSTEM_PROMPT = """당신은 우송대학교 학생들의 학교생활을 도와주는 AI 어시스턴트입니다.
학사 일정, 수강신청, 졸업요건, 장학금 등 학교생활 전반에 대해 친절하고 정확하게 안내해주세요.

반드시 지켜야 할 규칙:
1. 답변은 반드시 한국어로 작성하세요. 영어나 다른 언어를 절대 사용하지 마세요.
2. 문법과 맞춤법을 정확하게 사용하세요.
3. [참고 문서]가 제공된 경우, 반드시 해당 문서의 내용을 기반으로 답변하세요.
4. [참고 문서]에 없는 내용은 추측하지 말고, 학교 공식 홈페이지(wsu.ac.kr) 또는 담당 부서에 문의하도록 안내하세요.
5. 날짜, 기간, 절차 등 구체적인 정보는 문서에 있는 내용 그대로 정확하게 전달하세요.
6. 답변은 핵심 내용을 먼저 말하고, 필요한 경우 단계별로 설명하세요.
7. 불필요한 반복이나 장황한 설명은 피하세요."""

# 전용 스레드풀 (llama-cpp는 단일 스레드에서 실행)
_executor = ThreadPoolExecutor(max_workers=1)

_GGUF_PATH = "./llm/bllossom-8b-Q8_0.gguf"


class ChatService:
    def __init__(self):
        self.model: Llama | None = None

    def load_model(self):
        if settings.DEV_MODE:
            print("DEV_MODE: LLM 로딩 스킵")
            return

        print(f"모델 로딩 중: {_GGUF_PATH}")
        self.model = Llama(
            model_path=_GGUF_PATH,
            n_gpu_layers=28,    # RTX 3070 8GB 기준 (Q8_0 ~7.95GB)
            n_ctx=2048,
            n_batch=512,
            verbose=False,
        )
        print("모델 로딩 완료! (llama-cpp-python, GPU 28레이어)")

    def _generate(self, question: str) -> str:
        if settings.DEV_MODE:
            return f"[DEV_MODE] 질문 수신: {question}"

        try:
            t0 = time.time()
            print("[LLM] 추론 시작")

            response = self.model.create_chat_completion(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                ],
                max_tokens=512,
                temperature=0.3,
                top_p=0.9,
                repeat_penalty=1.2,
            )

            result = response["choices"][0]["message"]["content"]
            usage = response.get("usage", {})
            print(f"[LLM] 생성 완료 | 출력 토큰: {usage.get('completion_tokens', '?')} | 생성: {time.time()-t0:.1f}s")
            return result

        except Exception as e:
            print(f"[LLM] 추론 오류: {type(e).__name__}: {e}")
            raise

    async def answer(self, question: str) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._generate, question)


# 싱글톤 인스턴스
chat_service = ChatService()
