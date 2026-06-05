import asyncio
from functools import partial

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from app.core.config import settings

SYSTEM_PROMPT = """당신은 대학교 학생들의 학교생활을 도와주는 AI 어시스턴트입니다.
학사 일정, 수강신청, 졸업요건, 장학금 등 학교생활 전반에 대해 친절하게 안내해주세요.
모르는 내용은 모른다고 솔직하게 말하고, 학교 공식 홈페이지나 담당 부서에 문의하도록 안내하세요.
답변은 한국어로 작성해주세요."""


class ChatService:
    def __init__(self):
        self.tokenizer = None
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    def load_model(self):
        if settings.DEV_MODE:
            print("DEV_MODE: LLM 로딩 스킵")
            return

        print(f"모델 로딩 중: {settings.MODEL_PATH} (device: {self.device})")
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
        )
        self.model.eval()
        print(f"모델 로딩 완료!")
        if torch.cuda.is_available():
            print(f"VRAM 사용: {torch.cuda.memory_allocated(0)/1024**3:.2f} GB")

    def _generate(self, question: str) -> str:
        if settings.DEV_MODE:
            return f"[DEV_MODE] 질문 수신: {question}"

        try:
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

            # 모델이 있는 device로 이동
            inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
            input_ids = inputs["input_ids"]

            print(f"추론 시작...")

            with torch.no_grad():
                output_ids = self.model.generate(
                    input_ids,
                    max_new_tokens=128,
                    temperature=0.7,
                    do_sample=True,
                    pad_token_id=self.tokenizer.eos_token_id,
                    repetition_penalty=1.3,
                    eos_token_id=self.tokenizer.eos_token_id,
                )

            new_tokens = output_ids[0][input_ids.shape[-1]:]
            return self.tokenizer.decode(new_tokens, skip_special_tokens=True)

        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            print("CUDA OOM 발생! 캐시 정리")
            return "죄송합니다. 서버 메모리가 부족합니다. 잠시 후 다시 시도해주세요."
        except Exception as e:
            print(f"추론 오류: {type(e).__name__}: {e}")
            raise

    async def answer(self, question: str) -> str:
        return self._generate(question)


# 싱글톤 인스턴스
chat_service = ChatService()
