import asyncio
from concurrent.futures import ThreadPoolExecutor

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

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
            device_map={"": 0},

        )
        self.model.eval()
        device = next(self.model.parameters()).device
        print(f"모델 로딩 완료! 디바이스: {device}")

    def _generate(self, question: str) -> str:
        if settings.DEV_MODE:
            return f"[DEV_MODE] 질문 수신: {question}"

        try:
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

            print(f"[LLM] 토큰 길이: {input_ids.shape[-1]}")

            with torch.no_grad():
                output_ids = self.model.generate(
                    input_ids,
                    max_new_tokens=256,
                    temperature=0.3,
                    do_sample=True,
                    top_p=0.9,
                    pad_token_id=self.tokenizer.eos_token_id,
                    repetition_penalty=1.3,
                    eos_token_id=self.tokenizer.eos_token_id,
                )

            new_tokens = output_ids[0][input_ids.shape[-1]:]
            result = self.tokenizer.decode(new_tokens, skip_special_tokens=True)
            print("[LLM] 추론 완료")
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

