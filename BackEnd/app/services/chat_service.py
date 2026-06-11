import asyncio
from concurrent.futures import ThreadPoolExecutor

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from app.core.config import settings

SYSTEM_PROMPT = """
당신은 정확하게 답변하는 AI이다.

규칙:
- 반드시 한국어로 답변한다.
- 질문에 바로 답한다.
- 인사말을 하지 않는다.
- 자기소개를 하지 않는다.
- 역할을 설명하지 않는다.
- "궁금한 점이 있으신가요?"와 같은 추가 질문을 하지 않는다.
- 제공된 참고 문서가 있으면 반드시 참고 문서를 우선 사용한다.
- 참고 문서에 없는 내용은 추측하지 않는다.
- 모르면 공식 홈페이지 또는 담당 부서 확인을 안내한다.
- 불필요한 반복을 하지 않는다.
"""

# 전용 스레드풀 (CUDA는 단일 스레드에서 실행)
_executor = ThreadPoolExecutor(max_workers=1)


class ChatService:
    def __init__(self):
        self.tokenizer = None
        self.model = None

    def load_model(self):
        if settings.DEV_MODE:
            print("DEV_MODE: LLM 로딩 스킵")
            return

        print(f"모델 로딩 중: {settings.MODEL_PATH}")
        self.tokenizer = AutoTokenizer.from_pretrained(settings.MODEL_PATH)

        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        self.model = AutoModelForCausalLM.from_pretrained(
            settings.MODEL_PATH,
            quantization_config=bnb_config,
            torch_dtype=torch.float16,

            device_map="auto"
        )
        self.model.eval()
        device = next(self.model.parameters()).device
        print(f"모델 로딩 완료! 디바이스: {device}")

    def _generate(self, question: str) -> str:
        if settings.DEV_MODE:
            return f"[DEV_MODE] 질문 수신: {question}"

        import time
        try:
            t0 = time.time()
            print("[LLM] 추론 시작")
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ]

            text = self.tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                tokenize=False,
            )
            inputs = self.tokenizer(text, return_tensors="pt")
            inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
            input_ids = inputs["input_ids"]

            device = self.model.device
            print(f"[LLM] 디바이스: {device} | 입력 토큰: {input_ids.shape[-1]}")

            t1 = time.time()
            with torch.no_grad():
                output_ids = self.model.generate(
                    input_ids,
                    max_new_tokens=512,

                    temperature=0.1,
                    do_sample=True,
                    top_p=0.8,

                    pad_token_id=self.tokenizer.eos_token_id,
                    eos_token_id=self.tokenizer.eos_token_id,
                )
            t2 = time.time()

            new_tokens = output_ids[0][input_ids.shape[-1]:]
            result = self.tokenizer.decode(new_tokens, skip_special_tokens=True)
            print(f"[LLM] 생성 완료 | 출력 토큰: {len(new_tokens)} | 토크나이징: {t1-t0:.1f}s | 생성: {t2-t1:.1f}s")
            return result

        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            print("[LLM] CUDA OOM 발생!")
            return "죄송합니다. 서버 메모리가 부족합니다. 잠시 후 다시 시도해주세요."
        except Exception as e:
            print(f"[LLM] 추론 오류: {type(e).__name__}: {e}")
            raise

    async def answer(self, question: str) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._generate, question)


# 싱글톤 인스턴스
chat_service = ChatService()

