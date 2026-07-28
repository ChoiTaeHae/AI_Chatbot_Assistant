"""답변 후처리 번역 — 최종 답변 텍스트를 목표 언어로 번역한다.

LLM 생성 답변이든 코드 렌더링(동아리·제증명·카드)이든 '완성된 answer 문자열'을 통째로
번역하므로 전 경로가 다국어로 커버된다. Google Cloud Translation API(Vertex와 같은 GCP
프로젝트·서비스계정) 사용. text/plain으로도 마크다운·URL·전화번호를 보존한다(실측).

원칙:
- 한국어(ko) 요청은 번역하지 않는다(비용 0). 대상 언어(en/zh)만 번역.
- 실패·미설정 시 원문(한국어)으로 graceful fallback → 답변이 절대 깨지지 않는다.
- 원본(한국어)은 DB에 그대로 저장하고(진실 원천·파인튜닝용), 화면 표시분만 번역한다.
"""
import asyncio
import os

from app.core.config import settings

# 프론트 lang 코드 → Cloud Translation API 언어 코드. 여기 없는 값(ko 등)은 번역 안 함.
_LANG_MAP = {"en": "en", "zh": "zh-CN"}

_client = None


def _get_client():
    """TranslationServiceClient 싱글톤 (호출마다 재생성하면 비싸다)."""
    global _client
    if _client is None:
        from google.cloud import translate_v3 as translate
        if settings.GOOGLE_APPLICATION_CREDENTIALS:
            os.environ.setdefault(
                "GOOGLE_APPLICATION_CREDENTIALS", settings.GOOGLE_APPLICATION_CREDENTIALS
            )
        _client = translate.TranslationServiceClient()
    return _client


def _translate_sync(text: str, target_code: str) -> str:
    client = _get_client()
    parent = f"projects/{settings.GCP_PROJECT_ID}/locations/global"
    resp = client.translate_text(
        parent=parent,
        contents=[text],
        source_language_code="ko",   # 답변은 항상 한국어 생성 → 감지 생략(비용·오류 절감)
        target_language_code=target_code,
        mime_type="text/plain",
    )
    return resp.translations[0].translated_text


async def translate_answer(text: str, lang: str | None) -> str:
    """answer를 lang(en/zh)으로 번역. ko이거나 대상 아님/빈 문자열/실패면 원문 그대로 반환."""
    target = _LANG_MAP.get((lang or "").lower())
    if not target or not text or not text.strip():
        return text
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _translate_sync, text, target)
    except Exception as e:
        print(f"[Translation] 번역 실패 → 한국어 원문 유지: {type(e).__name__}: {e}")
        return text
