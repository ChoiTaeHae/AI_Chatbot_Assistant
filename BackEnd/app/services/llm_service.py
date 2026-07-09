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
from app.prompts import SYSTEM_PROMPT

# 전용 스레드풀 (llama-cpp는 단일 스레드에서 실행)
_executor = ThreadPoolExecutor(max_workers=1)


class LlmService:
    def __init__(self):
        self.model: Llama | None = None

    def load_model(self):
        # Gemini API 모드: 로컬 GGUF를 로딩하지 않고 API만 구성 (GPU VRAM 절약)
        if settings.LLM_PROVIDER == "gemini":
            if not settings.GEMINI_API_KEY:
                print("[LLM] ⚠️ LLM_PROVIDER=gemini인데 GEMINI_API_KEY가 비어있습니다. .env를 확인하세요.")
                return
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            print(f"[LLM] Gemini API 모드 — 모델: {settings.GEMINI_MODEL} (로컬 GGUF 로딩 스킵)")
            return

        if settings.DEV_MODE:
            print("DEV_MODE: LLM 로딩 스킵")
            return

        print(f"모델 로딩 중: {settings.MODEL_PATH}")
        self.model = Llama(
            model_path=settings.MODEL_PATH,

            n_gpu_layers=25,
            n_ctx=4096,
            n_batch=128,

            verbose=False,
        )
        print("모델 로딩 완료! (llama-cpp-python, GPU 15레이어)")

    def _generate(self, question: str, max_tokens: int = 512, system_prompt: str = SYSTEM_PROMPT, temperature: float = 0.3) -> str:
        if settings.DEV_MODE:
            return f"[DEV_MODE] 질문 수신: {question}"

        try:
            t0 = time.time()
            print("[LLM] 추론 시작")

            response = self.model.create_chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
                max_tokens=max_tokens,
                temperature=temperature,

                top_p=0.9,
                repeat_penalty=1.1,
            )
 
            result = response["choices"][0]["message"]["content"]
            usage = response.get("usage", {})
            print(f"[LLM] 생성 완료 | 출력 토큰: {usage.get('completion_tokens', '?')} | 생성: {time.time()-t0:.1f}s")
            return result

        except Exception as e:
            print(f"[LLM] 추론 오류: {type(e).__name__}: {e}")
            raise

    async def _generate_gemini(self, question: str, max_tokens: int = 512, system_prompt: str = SYSTEM_PROMPT, temperature: float = 0.3) -> str:
        """Gemini API로 답변 생성 (비동기)."""
        if settings.DEV_MODE:
            return f"[DEV_MODE] 질문 수신: {question}"

        import google.generativeai as genai

        t0 = time.time()
        print("[LLM] Gemini 추론 시작")
        try:
            model = genai.GenerativeModel(
                model_name=settings.GEMINI_MODEL,
                system_instruction=system_prompt,
            )
            resp = await model.generate_content_async(
                question,
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                    "top_p": 0.9,
                },
            )
            result = resp.text
            print(f"[LLM] Gemini 생성 완료 | 생성: {time.time()-t0:.1f}s")
            return result
        except Exception as e:
            print(f"[LLM] Gemini 추론 오류: {type(e).__name__}: {e}")
            raise

    async def answer(self, question: str, max_tokens: int = 512, system_prompt: str = SYSTEM_PROMPT, temperature: float = 0.3) -> str: #답변 최대 토큰수 지정
        # provider 스위치 — .env의 LLM_PROVIDER로 로컬/Gemini 전환
        if settings.LLM_PROVIDER == "gemini":
            return await self._generate_gemini(question, max_tokens, system_prompt, temperature)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._generate, question, max_tokens, system_prompt, temperature)



llm_service = LlmService()
