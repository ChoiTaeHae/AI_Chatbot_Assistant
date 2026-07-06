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
        if settings.DEV_MODE:
            print("DEV_MODE: LLM 로딩 스킵")
            return

        print(f"모델 로딩 중: {settings.MODEL_PATH}")
        self.model = Llama(
            model_path=settings.MODEL_PATH,
            n_gpu_layers=15,    # RTX 3070 8GB 기준 (Q8_0 ~7.95GB)
            n_ctx=8192,         # Llama-3 8B 지원 스펙에 맞춰 여유있게 확장
            n_batch=512,
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

    async def answer(self, question: str, max_tokens: int = 512, system_prompt: str = SYSTEM_PROMPT, temperature: float = 0.3) -> str: #답변 최대 토큰수 지정
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._generate, question, max_tokens, system_prompt, temperature)



llm_service = LlmService()
