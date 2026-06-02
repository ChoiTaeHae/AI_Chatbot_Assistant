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

    def load_model(self):
        """서버 시작 시 1번만 호출 - 모델을 GPU에 로드"""
        print(f"모델 로딩 중: {settings.MODEL_PATH}")

        self.tokenizer = AutoTokenizer.from_pretrained(settings.MODEL_PATH)

        # RTX 3070 8GB -> 4bit 양자화로 VRAM 절약
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )

        self.model = AutoModelForCausalLM.from_pretrained(
            settings.MODEL_PATH,
            quantization_config=bnb_config,
            device_map="auto",  # GPU 자동 할당
            torch_dtype=torch.float16,
        )
        self.model.eval()
        print("모델 로딩 완료!")

    def _generate(self, question: str) -> str:
        """동기 방식으로 텍스트 생성 (별도 스레드에서 실행)"""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]

        # 채팅 템플릿 적용
        input_ids = self.tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            return_tensors="pt",
        ).to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(
                input_ids,
                max_new_tokens=512,
                temperature=0.7,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id,
            )

        # 입력 부분 제거 후 답변만 디코딩
        new_tokens = output_ids[0][input_ids.shape[-1]:]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True)

    async def answer(self, question: str) -> str:
        """비동기로 답변 생성 (FastAPI 이벤트 루프 블로킹 방지)"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(self._generate, question))


# 싱글톤 인스턴스
chat_service = ChatService()
