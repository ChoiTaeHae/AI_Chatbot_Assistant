"""답변 후처리 번역 — 최종 답변 텍스트를 목표 언어로 번역한다.

LLM 생성 답변이든 코드 렌더링(동아리·제증명·카드)이든 '완성된 answer 문자열'을 통째로
번역하므로 전 경로가 다국어로 커버된다. Google Cloud Translation API(Vertex와 같은 GCP
프로젝트·서비스계정) 사용.

원칙:
- 한국어(ko) 요청은 번역하지 않는다(비용 0). 대상 언어(en/zh)만 번역.
- 실패·미설정 시 원문(한국어)으로 graceful fallback → 답변이 절대 깨지지 않는다.
- 원본(한국어)은 DB에 그대로 저장하고(진실 원천·파인튜닝용), 화면 표시분만 번역한다.

왜 통짜로 넘기지 않고 줄 단위로 나누는가
    answer 전체를 한 문자열로 보내면 API가 줄 사이에 빈 줄을 끼워 넣는다(실측 3/3 재현:
    4줄짜리 표 → 7줄, 빈 줄 3개 삽입). 마크다운에서 빈 줄은 표 블록을 끊기 때문에
    영어·중국어에서는 표가 파이프 문자 그대로 노출된다. 목록도 항목마다 빈 줄이 생겨
    간격이 벌어진다.

    그래서 줄로 쪼갠 뒤 번역할 줄만 골라 한 번의 요청으로 보내고(contents는 리스트를 받는다),
    받은 결과를 원래 줄 위치에 되꽂는다. 호출 횟수는 통짜로 보낼 때와 같은 1회다.

    빈 줄과 구분행(|---|, ---)은 번역 대상에서 제외한다 — 번역할 내용이 없는데 보내면
    엉뚱한 문자가 돌아와 표가 깨진다.

    줄 단위로 나눠도 문맥 손실이 거의 없는 이유는, 이 시스템의 답변이 줄바꿈으로 문단·항목을
    구분하고 한 줄이 곧 한 문장이나 한 항목이기 때문이다(문단 중간에서 줄을 접지 않는다).
"""
import asyncio
import os
import re

from app.core.config import settings

# 프론트 lang 코드 → Cloud Translation API 언어 코드. 여기 없는 값(ko 등)은 번역 안 함.
_LANG_MAP = {"en": "en", "zh": "zh-CN"}

# 번역할 내용이 없는 줄 — 표 구분행(|---|---|, |:--|--:|)과 수평선(---).
_SEPARATOR_RE = re.compile(r"^[\s|:\-]+$")

# 질문에 한글이 섞여 있는지. 화면 언어(lang)로 판정하면 안 된다 — 영어 화면을 켜 두고
# 한국어로 묻는 학생이 있고, 그때 번역을 태우면 멀쩡한 한국어 질문이 한 번 더 뒤틀린다.
_HANGUL_RE = re.compile(r"[가-힣]")

# 한 요청에 실을 최대 줄 수. 답변은 보통 수십 줄이라 대개 1회로 끝나지만,
# 아주 긴 답변에서 API의 세그먼트 상한에 걸리지 않도록 나눠 보낸다.
_MAX_SEGMENTS = 100

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


def _translate_sync(lines: list[str], target_code: str) -> list[str]:
    """줄 목록을 순서 그대로 번역해 돌려준다(입력 개수 = 출력 개수)."""
    client = _get_client()
    parent = f"projects/{settings.GCP_PROJECT_ID}/locations/global"
    out: list[str] = []
    for i in range(0, len(lines), _MAX_SEGMENTS):
        resp = client.translate_text(
            parent=parent,
            contents=lines[i:i + _MAX_SEGMENTS],
            source_language_code="ko",   # 답변은 항상 한국어 생성 → 감지 생략(비용·오류 절감)
            target_language_code=target_code,
            mime_type="text/plain",
        )
        out.extend(t.translated_text for t in resp.translations)
    return out


def _to_korean_sync(text: str) -> str:
    client = _get_client()
    parent = f"projects/{settings.GCP_PROJECT_ID}/locations/global"
    resp = client.translate_text(
        parent=parent,
        contents=[text],
        # source_language_code를 주지 않는다 → 자동 감지. 답변 번역과 달리 입력은 어떤
        # 언어로 올지 모른다(영어·중국어·그 외).
        target_language_code="ko",
        mime_type="text/plain",
    )
    return resp.translations[0].translated_text


async def translate_question_to_korean(question: str) -> str:
    """검색·라우팅에 쓸 한국어 질의를 만든다. 실패하면 원문 그대로.

    왜 필요한가 — 코퍼스도, 토픽 분류 문장도, 검색어 재작성 프롬프트도 전부 한국어다.
    비한국어 질문을 그대로 넣으면 재작성이 그 언어로 나와(실측: "How do I apply for a
    leave of absence?" → "How do I apply for a leave of absence") 한국어 문서를 찾지 못한다.
    질문을 입구에서 한국어로 옮기면 라우팅·검색·리랭킹이 전부 한국어와 같은 조건이 된다.

    한글이 하나라도 있으면 번역하지 않는다. 화면 언어가 영어라도 학생이 한국어로 물을 수
    있고, 그때 굳이 번역을 태우면 멀쩡한 질문이 왕복하며 뜻이 틀어진다(그리고 호출도 낭비다).
    """
    if not question or not question.strip():
        return question
    if _HANGUL_RE.search(question):
        return question
    try:
        loop = asyncio.get_event_loop()
        out = await loop.run_in_executor(None, _to_korean_sync, question)
        return out or question
    except Exception as e:
        print(f"[Translation] 질문 번역 실패 → 원문으로 검색: {type(e).__name__}: {e}")
        return question


async def translate_answer(text: str, lang: str | None) -> str:
    """answer를 lang(en/zh)으로 번역. ko이거나 대상 아님/빈 문자열/실패면 원문 그대로 반환."""
    target = _LANG_MAP.get((lang or "").lower())
    if not target or not text or not text.strip():
        return text

    lines = text.split("\n")
    targets = [
        i for i, ln in enumerate(lines)
        if ln.strip() and not _SEPARATOR_RE.match(ln.strip())
    ]
    if not targets:
        return text

    try:
        loop = asyncio.get_event_loop()
        translated = await loop.run_in_executor(
            None, _translate_sync, [lines[i] for i in targets], target
        )
        # 개수가 어긋나면 어느 줄이 어느 번역인지 알 수 없다. 잘못 끼워 맞추면 표의 셀이
        # 밀려 내용이 뒤바뀌므로, 그럴 바에는 한국어 원문을 그대로 보여 준다.
        if len(translated) != len(targets):
            print(f"[Translation] 줄 수 불일치({len(targets)}→{len(translated)}) → 원문 유지")
            return text
        for i, t in zip(targets, translated):
            lines[i] = t
        return "\n".join(lines)
    except Exception as e:
        print(f"[Translation] 번역 실패 → 한국어 원문 유지: {type(e).__name__}: {e}")
        return text
