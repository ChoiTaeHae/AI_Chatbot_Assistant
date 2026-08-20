"""
LangGraph 기반 학교 AI 에이전트

분류 흐름:
  pre_check → embedding_classify → (신뢰도 낮으면) llm_classify
                                  → 핸들러 노드 → END

라우팅 키: handler_type 문자열 (DB Topic.handler_type)
  "campus" / "graduation" / "scholarship" / "rag" / "general"
"""
import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from langgraph.graph import StateGraph, END
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_state import AgentState
from app.agents.topic_router import topic_router, SIMILARITY_THRESHOLD
from app.models.DB_Table import ChatLog
from app.services.llm_service import llm_service
from app.prompts import GENERAL_HANDLER_PROMPT
from app.services.school.campus import CampusService, has_building_hit, building_hit_alias
from app.services.school.department import answer_department_question
from app.services.school.dining import answer_dining_question_with_meta
from app.services.school.graduation import graduation_service
from app.services.school.my_grades import (
    my_grades_service,
    is_my_grades_question as _is_my_grades_question,
    is_grade_fragment as _is_grade_fragment,
)
from app.services.school.schedule import schedule_service
from app.services.school.rag_general import answer_rag_general_question_with_metadata, _rewrite_query, _distinctive_terms
from app.services.rag_service import rag_service
from app.services.file_service import AVAILABLE_FILES

_campus_service = CampusService()

_HIGH_CONFIDENCE = 0.60
# topic 전환 조건: 새 topic 점수가 이전 topic 점수보다 이 값 이상 높아야 전환
# (절대 임계값 대신 상대 비교 — 애매한 후속 질문은 유지, 명확한 주제 전환은 허용)
# 실측(26.07.03): 잘못된 전환(애매한 후속 질문)은 차이 0.037~0.106, 진짜 주제 전환은 0.182+
# → 그 사이인 0.15로 설정. 정상 전환이 막히는 로그가 보이면 하향 검토
_SWITCH_MARGIN = 0.15

# prev_topic이 RAG 토픽(_proto_vecs)이 아니라 핸들러명으로 저장되는 경우
# (graduation/campus/general/scholarship 핸들러의 topic은 DB RAG 토픽이 아님)
_NON_RAG_HANDLERS = {"campus", "graduation", "scholarship", "schedule", "general", "my_grades"}

_BUILDING_CODE_RE = re.compile(r'^[WwEeSs]\d{1,2}$')

def _is_campus_question(q: str) -> bool:
    return bool(_BUILDING_CODE_RE.search(q))


# 위치 의도어 — '어디/위치/어딨/가는 길' 등.
_LOCATION_INTENT_RE = re.compile(r'어디|어딨|어디에|위치|찾아가|가는\s*길|어느\s*건물|몇\s*층|몇\s*호')
# 정보·절차 의도어 — 이게 있으면 '위치'가 아니라 그 주제의 정보/절차 질문이다.
# 건물명이 매칭돼도 정보의도가 있으면 campus로 보내지 않는다.
# ('학군단 뭐야/소개/모집 언제' → RAG, '학군단'·'학군단 어디' → campus 위치)
_INFO_INTENT_RE = re.compile(
    r'뭐|뭔|무엇|어떤|소개|알려|설명|신청|방법|어떻게|언제|얼마|며칠|기간|'
    # '요건'은 '자격|조건'과 같은 층위인데 빠져 있었다. 실측: '솔브릿지국제경영대학 졸업요건'이
    # 건물 별칭 '솔브릿지'에 걸려 지도로 답했고, 그 바람에 단과대→소속학과 되묻기가 아예 안 보였다.
    r'지원|모집|혜택|자격|조건|요건|정보|대해|되나|하나요|인가요|추천|목록|'
    # 시설 이용·대여·예약 등 '서비스/절차' 질문 — 위치가 아니라 그 정보(RAG)를 원하는 것
    # '몇 시'(운영/개관 시간)는 정보 질문 — '시간'은 있는데 '몇 시까지 해'가 안 걸려 '도서관 몇
    # 시까지 해'가 지도로 답하던 문제(실측). '몇 층/몇 호'는 _LOCATION_INTENT_RE라 위치 유지.
    r'대여|대관|예약|이용|사용|빌리|운영|시간|몇\s*시|요금|가격|비용|'
    # 시설 '서비스' 질문 — 건물명이 걸려도 위치가 아니라 그 서비스 정보다.
    # ('기숙사 와이파이 비번'이 건물명 '기숙사'에 걸려 지도로 답하던 문제 — 실측)
    r'와이파이|wifi|비번|비밀번호|택배|세탁|충전|보관|분실|'
    # 식사 관련어 — 건물명이 걸려도 묻는 건 위치가 아니라 그날 메뉴다.
    # 실측: '토요일 기숙사 식단'이 건물명 '기숙사'에 걸려 캠퍼스 지도로 답했다.
    # ('식당'은 넣지 않는다 — "학생식당 어디야"는 위치 질문이 맞아서 지도가 옳다)
    r'식단|학식|메뉴'
)
# 행위(획득·발급·신청·대여·예약 등) 동사 — 위치 의도('어디')가 있어도 이게 있으면 campus 억제.
# '어디서 받아요'는 '동아리방이 어디냐'가 아니라 '열쇠를 어디서 받냐'는 절차 질문이라, 건물 별칭이
# 우연히 잡혀도(예: '동아리방 열쇠 어디서 받아요' → 학생회관 별칭 '동아리방') 지도 대신 RAG/FAQ로.
# ('동아리방 어디야?' 같은 순수 위치질문은 행위어가 없어 그대로 campus로 간다)
_PROCEDURE_RE = re.compile(r'열쇠|받아|받을|받나|받으러|받는|받고|받습|발급|신청|빌리|빌려|대여|반납|예약|대출')

# 위치 질문에서 건물명 외에 붙어도 '내용어'로 치지 않는 말들 — 조사·어미·군말.
# ('학생회관 어디야?' → 건물명 빼면 '어디야'만 남고, 이건 순수 위치 질문이다)
_CAMPUS_FILLER_RE = re.compile(
    r'어디|어딨|어디에|위치|찾아|가는|길|건물|층|호|가려면|가면|알려|줘|주세요|해줘|'
    r'좀|는|은|이|가|을|를|의|에|에서|로|으로|야|요|입니다|인가|인가요|있어|있나|있나요|'
    r'뭐야|어느|어떻게\s*가|무슨\s*건물|보여|알고|싶어|궁금|\?|!|\.|,'
)


async def _campus_gate(q: str) -> bool:
    """건물명이 잡혔을 때 '지도로 답할 질문인지' 판정.

    예전 조건은 "정보 의도어(_INFO_INTENT_RE)가 없으면 지도"였는데, 기본값이 지도라
    사전에 없는 표현이 나올 때마다 엉뚱하게 지도가 떴다(두더지잡기). 실측 사례:
      '기숙사 입사 제한 대상은?' → '입사/제한/대상'이 정보어 목록에 없어 → 지도(유학생기숙사)
    그래서 판정을 뒤집는다 — **건물명을 떼고도 내용어가 남으면 그건 정보 질문**이다.
      · '기숙사'            → 남는 말 없음        → 지도 O
      · '학생회관 어디야?'  → '어디야'(군말)만    → 지도 O
      · '기숙사 입사 제한 대상은?' → '입사 제한 대상' 남음 → 지도 X (RAG로)
    명시적 위치 의도(어디/위치/몇 층…)가 있으면 내용어가 남아도 위치 질문으로 본다.
    """
    alias = await building_hit_alias(q)
    if not alias:
        return False
    if _LOCATION_INTENT_RE.search(q):
        return True
    # 건물 별칭(공백 무시 매칭이므로 원문에서도 공백 무시하고) 제거 후 남는 내용어 확인
    rest = re.sub(re.escape(alias), " ", q.replace(" ", ""), flags=re.IGNORECASE)
    rest = _CAMPUS_FILLER_RE.sub(" ", rest)
    rest = re.sub(r'[\s\W_]+', "", rest)
    if rest:
        print(f"[Graph] 건물명 '{alias}' 매칭됐지만 내용어 '{rest}' 남음 → campus 아님")
        return False
    return True


# 학사일정 '날짜 질문' fast-path — 날짜 의도(언제/며칠/언제까지…) + 학사 이벤트 키워드면
# 임베딩 tug-of-war 없이 schedule로 확정 라우팅한다. 성적·휴학처럼 grades/leave/graduation과
# 심하게 겹치는 단어도, "언제/기간이 언제까지" 같은 날짜 의도가 붙으면 답은 항상 달력(DB)이 맞다.
# 날짜 의도가 없으면(조회 "성적 알려줘", 절차 "휴학 어떻게") 걸리지 않아 기존 토픽이 유지된다.
#
# ★ 키워드는 DB(app_config, key="schedule_gate")에서 로드해 어드민이 편집 가능. 아래는 기본값(시딩용).
#   set_schedule_gate()로 런타임 교체되고, 어드민 저장 시 즉시 반영(재시작 불필요).
DEFAULT_DATE_INTENT = ['언제', '며칠', '몇월', '몇일', '날짜', '언제까지', '언제부터']
DEFAULT_EVENT_KWS = [
    '수강신청', '수강정정', '수강변경', '수강철회', '수강취소',
    '개강', '종강', '개학', '방학', '휴학', '복학', '자퇴', '전과', '재입학',
    '등록기간', '분납',
    '성적정정', '성적입력', '성적공고', '이의신청', '성적',
    '중간고사', '기말고사', '정기평가', '수시평가', '시험기간',
    '보강', '계절학기', '여름학기', '겨울학기',
    '입학식', '졸업식', '학위수여식', '종합시험', '전공배정', '복수전공', '부전공',
]

# 게이트 배제어 — 날짜의도어+이벤트어가 다 있어도, 이 중 하나라도 있으면 게이트를 발동하지
# 않고 임베딩 라우터로 넘긴다. 게이트 이벤트어에는 휴학·복학처럼 '전용 토픽'이 따로 있는
# 단어가 많아, '복학 등록금 언제 내'가 통째로 schedule로 확정돼 신청 마감일을 엉뚱하게
# 답하는 버그가 있었다(실측). 절차·납부·서류를 묻는 질문은 날짜 질문이 아니라 그 토픽의
# 절차 질문이므로 임베딩이 판단하게 한다.
#   포함: 등록금·납부(등록금 절차), 서류·제출·신청서(서류), 방법·절차·어떻게(절차)
#   제외: 취소·철회 — event_kw '수강취소/수강철회'와 부분 매칭돼 정당한 일정 질문을 막는다.
GATE_EXCLUDE = ('등록금', '납부', '서류', '제출', '신청서', '방법', '절차', '어떻게')

# ── 프롬프트 인젝션 입력 필터 ─────────────────────────────────────
# LLM에 닿기 전에 '노골적인' 조작 시도만 선차단하는 보조 방어 겹(프롬프트 하드닝의 백업).
# 원칙: 정상 학사 질문에는 절대 나오지 않는 조합만 좁게 매칭 → 오탐(정상 질문 차단)을 0에 가깝게.
#       (여기 안 걸리는 정교한 시도는 시스템 프롬프트의 지시계층 방어가 받아낸다)
# 튜닝: 오탐이 생기면 해당 패턴만 지우면 되고, 통째로 끄려면 _looks_like_injection이 항상 None 반환.
_INJECTION_PATTERNS = (
    # 1) 이전 지시/규칙/프롬프트를 무시·삭제·망각하라는 메타 지시 ('무시' 등 동사와 결합될 때만)
    r"(이전|앞의|위의|기존|모든)\s*(의)?\s*(지시|명령|규칙|프롬프트|설정|제약)\w*.{0,5}?(무시|잊|삭제|해제|무효)",
    r"ignore\s+(all\s+|the\s+|previous\s+|prior\s+|above\s+)*(instruction|prompt|rule|command|guideline)",
    r"disregard\s+(all\s+|the\s+|previous\s+|prior\s+|above\s+)*(instruction|prompt|rule)",
    # 2) 역할/정체성 강제 변경 (규칙·제한·필터 없는 AI 요구, DAN 등)
    r"(규칙|제한|필터|검열|제약)\s*[이가]?\s*없는\s*(AI|인공지능|챗봇|코파일럿|모델|assistant|어시스턴트)",
    r"(이제부터|지금부터)\s*(너|넌|당신|니)\S*.*(규칙\s*없|제한\s*없|필터\s*없|뭐든|무엇이든|다른\s*AI|역할\s*을?\s*바꾸)",
    r"pretend\s+you\s+are|you\s+are\s+now\s+(a|an|dan)\b|act\s+as\s+(a\s+)?(dan|jailbroken)",
    # 3) 시스템/개발자 프롬프트 유출 요구
    r"(시스템|개발자|system|developer)\s*(프롬프트|prompt|지시|instruction|메시지|message)\w*\s*[을를]?\s*(그대로|전부|모두)?\s*(알려|보여|출력|공개|말해|뱉|노출|reveal|show|print|repeat)",
    r"(프롬프트|prompt)\s*[을를]?\s*(그대로|전부|모두)\s*(출력|공개|보여|알려|repeat|print)",
    # 4) 우리 내부 입력 레이블을 사용자가 직접 주입(역할/구획 스푸핑)
    r"\[\s*(시스템|system|개발자|developer|assistant|참고\s*문서|사용자\s*질문)\s*\]",
    # 5) 노골적 탈옥 키워드
    r"jailbreak|dan\s*(모드|mode)|탈옥\s*모드",
)
_INJECTION_RE = tuple(re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS)
_INJECTION_REPLY = (
    "죄송해요, 그 요청은 도와드리기 어려워요. 저는 우송대학교 학사(수강신청·졸업·장학금 등) "
    "질문을 도와드리는 코파일럿이에요. 학사 관련해서 궁금한 점을 편하게 물어봐 주세요! 😊"
)


def _looks_like_injection(q: str) -> str | None:
    """노골적 프롬프트 인젝션이면 매칭된 패턴(로깅용)을, 아니면 None을 반환."""
    if not q:
        return None
    for rx in _INJECTION_RE:
        if rx.search(q):
            return rx.pattern
    return None


# 런타임 캐시 (공백 제거 비교 기준)
_gate_date_intent = tuple(k.replace(' ', '') for k in DEFAULT_DATE_INTENT)
_gate_event_kws = tuple(k.replace(' ', '') for k in DEFAULT_EVENT_KWS)


def set_schedule_gate(date_intent: list[str] | None, event_keywords: list[str] | None) -> None:
    """DB 설정으로 게이트 키워드를 런타임 교체. 빈 값이면 기본값 유지."""
    global _gate_date_intent, _gate_event_kws
    di = [k.replace(' ', '') for k in (date_intent or []) if k and k.strip()]
    ek = [k.replace(' ', '') for k in (event_keywords or []) if k and k.strip()]
    _gate_date_intent = tuple(di) if di else tuple(k.replace(' ', '') for k in DEFAULT_DATE_INTENT)
    _gate_event_kws = tuple(ek) if ek else tuple(k.replace(' ', '') for k in DEFAULT_EVENT_KWS)
    print(f"[Graph] 학사일정 게이트 갱신: 날짜의도 {len(_gate_date_intent)}개 / 이벤트 {len(_gate_event_kws)}개")


def _is_schedule_date_question(q: str) -> bool:
    qn = q.replace(' ', '')
    if any(x in qn for x in GATE_EXCLUDE):   # 절차·납부·서류 질문이면 날짜 fast-path 금지
        return False
    if not any(d in qn for d in _gate_date_intent):
        return False
    return any(kw in qn for kw in _gate_event_kws)


def _with_file_offer(updates: dict, topic: str, question: str = "") -> dict:
    files_to_offer = updates.pop("files_to_offer", [])
    if not files_to_offer:
        return updates

    # 실제 AVAILABLE_FILES에 있는 파일과 매칭 (확장자 포함된 원본 파일명 찾기)
    actual_files = AVAILABLE_FILES.get(topic, [])
    matched_actual_files = []
    for target in files_to_offer:
        for actual in actual_files:
            if target == Path(actual).stem:
                matched_actual_files.append(actual)
                break

    if not matched_actual_files:
        return updates

    if len(matched_actual_files) == 1:
        stem = Path(matched_actual_files[0]).stem
        offer_text = f"\n\n혹시 **{stem}** 파일이 필요하시면 보내드릴까요?"
    else:
        offer_text = f"\n\n관련 파일이 {len(matched_actual_files)}개 있어요. 드릴까요?"

    return {
        **updates,
        "answer": updates["answer"] + offer_text,
        # show_buttons=False: 첫 응답에는 버튼 숨김, '응' 입력 후에 True로 전환
        "file_offer": {"topic": topic, "files": matched_actual_files, "show_buttons": False},
    }


def _build_prev_prefix(state: AgentState) -> str:
    """이전 대화가 있으면 프롬프트 앞에 붙일 맥락 문자열 생성.
    topic이 바뀌었으면 이전 맥락을 전달하지 않음 (LLM이 이전 topic 질문으로 혼동).

    [이전 질문]+[이전 답변] → LLM이 이전 답변 반복
    [이전 질문]만 → LLM이 이전 질문에 답하려 함
    "이전 주제:" 형식 → 맥락 힌트만 부여, LLM이 답변 대상으로 인식 안 함"""
    prev = state.get("prev_context")
    if not prev:
        return ""
    prev_topic = prev.get("prev_topic")
    current_topic = state.get("topic")
    if prev_topic and current_topic and prev_topic != current_topic:
        return ""
    pq = prev.get("prev_question", "")
    if not pq:
        return ""
    return f"이전 주제: {pq}\n\n"


def _append_contact_info(answer: str, metadata: dict) -> str:
    """답변 뒤에 출처 URL, 담당 부서, 전화번호를 붙인다."""
    # 답변 자체가 '자료 못 찾음'이면 잡았던(무관) 문서의 출처·연락처를 붙이지 않는다.
    # (예: '파이썬 코드 짜줘'가 무관 문서를 잡아 못찾음 답 → campus 출처·교무팀 전번이 오해를 준다)
    _NOT_FOUND = ("찾지 못", "찾을 수 없", "제공된 문서에", "관련 자료가 없", "관련 자료를 찾")
    if any(m in answer for m in _NOT_FOUND):
        return answer
    parts = []
    url = metadata.get("url")
    contact_name = metadata.get("contact_name")
    contact_phone = metadata.get("contact_phone")
    if url:
        parts.append(f"출처: [{url}]({url})")
    if contact_name and contact_phone:
        parts.append(f"문의: {contact_name} {contact_phone}")
    elif contact_name:
        parts.append(f"문의: {contact_name}")
    elif contact_phone:
        parts.append(f"문의: {contact_phone}")
    if parts:
        return answer + "\n\n" + "  \n".join(parts)
    return answer


async def _log(db: AsyncSession, student_id: int | None, intent: str) -> None:
    try:
        db.add(ChatLog(student_id=student_id, intent=intent))
        await db.commit()
    except Exception as e:
        print(f"[Graph] 채팅 로그 저장 실패 (무시): {e}")


# ── 노드 함수들 ────────────────────────────────────────────────────

async def _pre_check(state: AgentState) -> dict:
    """파일 확인 응답 및 멀티턴 컨텍스트 처리

    file_confirm: 프론트 예/아니오 버튼에서 전달된 명시적 값
      True  → 파일 전송 (또는 파일 선택 버튼 표시)
      False → 거절 메시지
      None  → 파일 응답이 아님, 일반 질문으로 처리
    """
    # 프롬프트 인젝션 입력 필터 — 노골적 조작 시도는 LLM/검색을 태우지 않고 즉시 정중히 거절.
    # (파일 예/아니오 버튼 흐름엔 question이 비어/무해하므로 걸리지 않는다)
    inj = _looks_like_injection(state.get("question", ""))
    if inj:
        print(f"[Graph] 입력 인젝션 패턴 차단: '{state.get('question','')[:60]}' | 패턴={inj}")
        return {"answer": _INJECTION_REPLY, "done": True}

    pf = state.get("pending_file")
    file_confirm = state.get("file_confirm")  # bool | None

    # pending_context(팀원 멀티턴)가 활성 중이면 파일 체크를 건너뜀
    if pf and file_confirm is not None and not state.get("pending_context"):

        if file_confirm is False:  # 아니오 버튼
            return {
                "answer": "알겠습니다! 다른 궁금하신 점이 있으시면 언제든지 질문해 주세요. 😊",
                "done": True,
            }

        if file_confirm is True:  # 예 버튼
            # 단일 파일: 기존 키(filename) 또는 files 리스트 1개짜리
            filename = pf.get("filename") or (
                pf["files"][0] if pf.get("files") and len(pf["files"]) == 1 else None
            )
            if filename:
                stem = Path(filename).stem
                return {
                    "answer": f"네, {stem} 보내드릴게요!",
                    "file_download": {
                        "topic": pf["topic"],
                        "filename": filename,
                        "url": f"/api/files/{pf['topic']}/{filename}",
                    },
                    "source": "file_download",
                    "source_file": filename,
                    "topic": pf["topic"],
                    "done": True,
                }
            # 파일이 2개 이상 → 파일 선택 버튼 표시
            if pf.get("files") and len(pf["files"]) > 1:
                return {
                    "answer": "어떤 파일이 필요하신가요? 아래에서 골라주세요!",
                    "file_offer": {"topic": pf["topic"], "files": pf["files"], "show_buttons": True},
                    "done": True,
                }

    # 진행 중인 멀티턴 → context type을 intent로 세팅해서 해당 핸들러로 직행
    if state.get("pending_context"):
        ctx_type = state["pending_context"].get("type", "general")
        return {"intent": ctx_type, "done": False}

    # 국가장학금 검수 FAQ 게이트 — 장학금류 질문이면 '라우팅 전에' Qdrant 검수 Q&A를 먼저 확인한다.
    # → 장학금 포스터 RAG가 특정 학기 날짜로 엉뚱하게 답하기 전에 검수 답변이 이긴다.
    # 멀티턴: 후속 질문("어떻게 신청해?")엔 장학금 단어가 없으니, 직전이 장학금 맥락이면
    #   '국가장학금'을 붙여 보강해 조회한다("국가장학금 어떻게 신청해?"). 임계값 미만이면 통과(설문 등).
    q = state.get("question", "")
    _prev = state.get("prev_context") or {}
    prev_q = _prev.get("prev_question", "") or ""
    prev_topic = _prev.get("prev_topic", "") or ""
    _SCH_KW = ("장학금", "국장", "국가장학", "학자금")
    faq_q = None
    if q and _is_scholarship_browse(q):
        # '무슨 장학금 있어?'·'추천해줘'는 정의 FAQ가 아니라 설문·카테고리 카드가 답이다.
        # 여기서 걸러 두지 않으면 임베딩이 '장학금'만 보고 정의 FAQ를 물어온다.
        print(f"[Graph] 장학금 목록·추천 질문 → 검수 FAQ 건너뜀: '{q[:40]}'")
    elif q and any(k in q for k in _SCH_KW):
        faq_q = q
    elif q and (prev_topic == "scholarship" or any(k in prev_q for k in _SCH_KW)):
        # 후속 질문 — 직전이 장학금 맥락(직전 답변 topic 또는 직전 질문 키워드)이면 '국가장학금' 붙여 보강.
        # (직전 답변 topic까지 봐서 "국장?→어떻게?→매 학기?"처럼 키워드 없는 후속이 이어져도 체인 유지)
        faq_q = "국가장학금 " + q
    if faq_q:
        verbatim = await asyncio.get_event_loop().run_in_executor(None, _lookup_scholarship_faq, faq_q)
        if verbatim:
            return {"answer": verbatim, "source": "scholarship_faq", "source_file": None,
                    "topic": "scholarship", "done": True}

    return {"done": False}


def _resolve_prev_route(prev_topic: str | None) -> tuple[str | None, str | None]:
    """이전 topic으로부터 (handler_intent, topic_filter)를 결정한다.

    - prev_topic이 RAG 토픽(_proto_vecs에 존재) → 그 핸들러 + 토픽 필터
    - prev_topic이 핸들러명(graduation/campus/general/scholarship) → 그 핸들러로 직행
      (RAG 토픽 필터가 아니므로 rag 핸들러로 잘못 보내 검색 0건 나는 것을 방지)
    - 그 외(알 수 없음) → (None, None): 스티키니스 미적용
    """
    if not prev_topic:
        return None, None
    proto = topic_router._proto_vecs.get(prev_topic) if topic_router._proto_vecs else None
    if proto:
        return proto.get("handler_type", "rag"), prev_topic
    if prev_topic in _NON_RAG_HANDLERS:
        return prev_topic, prev_topic
    return None, None


# 흔한 인사/호응 잡담 fast-path (임베딩 없이 0비용). 완전할 필요 없음 —
# 놓친 개방형 잡담은 아래 임베딩 게이트가 잡는다. $ 앵커로 실제 질문 오탐 방지.
_CHITCHAT_RE = re.compile(
    r'^\s*((오+|와+|우와+|아+|어+|헐+|음+|흠+|이야)\s+)?'   # 선택적 감탄사 prefix ("오 ", "와 ")
    r'(ㅋ+|ㅎ+|안녕(하세요)?|반가워요?|고마워요?|고맙습니다|감사(합니다|해요|해|드려요)?|ㄳ|ㄱㅅ|땡큐|thanks?|thank you|'
    r'넵|네+|응+|ㅇㅇ|ㅇㅋ|오케이?|오키|알겠(습니다|어요|어)?|알았어요?|굿|좋아요?|좋네요?|good|great|ok(ay)?|'
    r'와+|우와+|대박(이다|이네|이야)?|신기(하다|하네요?|해요|해|하군)?|헐|음+|흠+|짱|멋지다|멋있어요?|재밌|재미있|웃기|쩐다|쩔어|놀랍|'
    r'그렇구나|그렇군요?|그렇네요?|그렇다|그렇답니다|그런거구나|그런거네요?|그러네요?|아하+|오호+|이해했어요?|이해돼요?|이해됐어요?)'
    r'\s*[.!~?ㅋㅎ]*\s*$',
    re.IGNORECASE,
)

# 챗봇 자기소개는 잡담 핸들러가 답하는데(_SELFINTRO_RE), 라우터가 먼저 다른 데로 보내버리는
# 표현이 있다 — 실측으로 '자기소개 해줘'는 학과소개로 빠져 "어느 학과를 말씀하시는지" 되묻고,
# '사용법 알려줘'는 RAG로 빠져 0건이 났다. 이 둘만 라우팅보다 앞에서 잡는다.
# _SELFINTRO_RE 전체를 여기로 올리면 안 된다 — '뭐 할 수 있어'가 '동아리 뭐 할 수 있어?'를,
# '소개 해'가 '간호학과 소개해줘'를 삼킨다. 그래서 대상이 앞에 붙을 수 없는 형태로만 좁혔다:
# '사용법'은 문두 한정('도서관 사용법' 제외), '자기소개'는 '자기소개서'만 배제.
_SELFINTRO_GATE_RE = re.compile(r'자기\s*소개(?!서)|^\s*사용법')


async def _chitchat_gate(state: AgentState) -> dict:
    """rewrite 앞 잡담 감지 게이트 (후속질문 전용).

    잡담은 지식 질문이 아니라 rewrite/검색 파이프라인에 들어가면 안 된다.
    후속 잡담("감사합니다")이 rewrite를 타면 이전 topic으로 재작성돼 오라우팅되므로,
    rewrite 이전에 걸러 잡담 핸들러로 직행시킨다.
      - 1차 질문(맥락 없음): 기존 흐름이 잡담을 처리하므로 게이트 skip.
      - 후속질문: 정규식 fast-path로만 감지.

    ※ 임베딩 게이트는 제거함 — "조건이 어떻게되니?" 같은 애매한 학사 파편을 general로
      오분류해 rewrite 기회를 뺏는 문제가 있었다. 정규식이 놓친 후속은 rewrite로 넘겨
      이전 질문과 합쳐 토픽 질문으로 만든 뒤 2차 라우팅에 맡긴다.
    """
    # 자기소개는 후속질문이 아니라 '처음 켜자마자' 던지는 1차 질문이 대부분이라, prev 체크보다
    # 앞에 둔다(아래 skip에 걸리면 라우터로 넘어가 학과소개·RAG로 새버린다).
    if _SELFINTRO_GATE_RE.search(state["question"]):
        print(f"[Graph] 챗봇 자기소개 매치 → 잡담 핸들러 직행: '{state['question']}'")
        return {"intent": "general", "topic": "general", "confidence": 1.0}

    prev = state.get("prev_context")
    if not (prev and prev.get("prev_question")):
        return {}   # 1차 질문 → 게이트 skip

    # 정규식 fast-path만 사용 ($ 앵커라 학사 파편 오탐 없음, 흔한 인사/호응만 잡음)
    if _CHITCHAT_RE.match(state["question"]):
        print(f"[Graph] 잡담 정규식 매치 → 잡담 핸들러 직행: '{state['question']}'")
        return {"intent": "general", "topic": "general", "confidence": 1.0}
    return {}


async def _rewrite(state: AgentState) -> dict:
    """후속질문(이전 맥락 존재)일 때만 질문을 rewrite해서 search_query로 저장.

    A 설계: rewrite 결과로 2차 라우팅(embedding_classify)과 검색을 모두 수행한다.
      - 후속이면 rewrite가 이전 주제를 보충("기간은?"→"휴학 기간")하거나,
        새 주제면 이전을 버리고 현재 질문만 남긴다(프롬프트 규칙).
      - 1차 질문(맥락 없음)은 여기서 건너뛰고 rag_general 내부 rewrite에 맡긴다.
    """
    prev = state.get("prev_context")
    prev_question = prev.get("prev_question") if prev else None
    if not prev_question:
        return {}
    try:
        rewritten = await _rewrite_query(state["question"], prev_question=prev_question)
    except Exception as e:
        print(f"[Graph] 후속질문 rewrite 실패(원본으로 진행): {e}")
        return {}
    print(f"[Graph] 후속질문 rewrite: '{state['question']}' → '{rewritten}' (이전: '{prev_question}')")
    # DB 로깅(파인튜닝 데이터)용: 어느 핸들러로 라우팅되든 여기서 rewritten_query를 기록한다.
    # (실제로 재작성된 경우만 — 드리프트 폴백으로 원본과 같으면 None)
    return {
        "search_query": rewritten,
        "rewritten_query": rewritten if rewritten != state["question"] else None,
    }


async def _embedding_classify(state: AgentState) -> dict:
    """임베딩 유사도 기반 분류 — (topic_name, handler_type, score, all_scores) 사용.

    후속질문이면 search_query(rewrite 결과)로 라우팅한다(2차 라우팅). 1차 질문은 원본으로.
    """
    loop = asyncio.get_event_loop()
    route_query = state.get("search_query") or state["question"]
    # 검색어 딕셔너리를 '라우팅에도' 적용한다. 지금까지는 검색 단계에만 걸려서, 구어·오타
    # 표기가 엉뚱한 토픽으로 확정되면 그 토픽 문서만 뒤지다 0건이 됐다.
    # 실측: '재증명이 뭐야?'가 '재-' 때문에 readmission(0.574)으로 새고 재입학 문서만 검색 →
    # 못 찾음. 공식어 '증명서'를 붙이면 rag_general(0.670)로 바로잡힌다.
    # (학칙→학생규칙, 공결→출석인정 등 기존 매핑은 토픽이 그대로라 회귀 없음 — 실측 확인)
    try:
        from app.services.school.rag_general import expand_search_query
        route_query = expand_search_query(route_query)
    except Exception as e:
        print(f"[Graph] 라우팅 딕셔너리 확장 실패(원본으로 진행): {e}")
    try:
        topic_name, handler_type, score, all_scores = await loop.run_in_executor(
            None, topic_router.route_with_score, route_query
        )
        print(f"[Graph] 임베딩 분류 → topic={topic_name} handler={handler_type} ({score:.3f})")

        prev = state.get("prev_context")
        prev_topic = prev.get("prev_topic") if prev else None
        # 잡담(general)은 stickiness 앵커가 되지 않음 — 잡담 한마디로 진행 중이던
        # RAG 맥락이 끊기고 근거 없는 general 답변에 갇히는 것을 방지 (2차 방어선,
        # 1차는 chat_service의 prev_context 구성 단계에서 잡담을 건너뛰는 것)
        if prev_topic == "general":
            prev_topic = None

        # 저신뢰(< _HIGH_CONFIDENCE)이고 새 topic이 이전 topic보다 _SWITCH_MARGIN 이상
        # 우세하지 못하면 → 이전 topic 유지(stickiness). 확신이거나 명확히 우세하면 전환.
        # ("공결신청하고싶어"가 absence=0.728로 확실한데 이전 graduation에 갇히는 것 방지)
        # ※ 기존 블록 2와 통합함 — 블록 2의 '이전 topic 유지' return은 prev_handler가 falsy일
        #    때만 도달해 실제로는 늘 새 topic(handler_type)을 반환하던 죽은/오해 코드라 제거.
        #    실질 stickiness는 이 블록 하나로 충분(margin 판정 중복 제거).
        # 현재 질문에 뚜렷한 주제어가 있으면 = 스스로 주제를 특정하는 '완결된 새 질문'이므로
        # stickiness를 건너뛴다. stickiness는 '기간은?' 같은 주제어 없는 파편 후속질문을 이전
        # 맥락으로 잇기 위한 것인데, 'WS인증 어학 기준'(주제어 WS인증)처럼 완결된 질문이 우연히
        # 이전 topic과 임베딩이 가까우면(공결 absence=0.424) 엉뚱하게 갇혔다(실측: graduation
        # 0.553이 1등인데 absence로 강제). 주제어 유무로 파편/완결을 가른다(rewrite 가드와 동일 원리).
        has_own_topic = bool(_distinctive_terms(state["question"]))
        if score < _HIGH_CONFIDENCE and prev_topic and not has_own_topic:
            prev_cmp_score = all_scores.get(prev_topic) or 0.0
            if score - prev_cmp_score < _SWITCH_MARGIN:
                prev_handler, prev_route_topic = _resolve_prev_route(prev_topic)
                if prev_handler:
                    print(
                        f"[Graph] 저신뢰 & 이전 대비 우세 미달 "
                        f"(새 {topic_name}={score:.3f} vs 이전 {prev_topic}={prev_cmp_score:.3f}, "
                        f"차이 {score - prev_cmp_score:.3f} < {_SWITCH_MARGIN}) → 이전 topic 유지 (handler={prev_handler})"
                    )
                    return {"intent": prev_handler, "topic": prev_route_topic, "confidence": score}
                # prev_topic 해석 불가 → 새 분류로 진행
            elif topic_name != prev_topic:
                print(
                    f"[Graph] topic 전환 승인 (새 {topic_name}={score:.3f} vs "
                    f"이전 {prev_topic}={prev_cmp_score:.3f}, 차이 {score - prev_cmp_score:.3f} ≥ {_SWITCH_MARGIN})"
                )

        # 확신도가 게이트 미만이면 _route_embedding이 이 topic을 버리고 rag로 폴백시킨다.
        # 그 경우에만 topic의 문서 수를 확인한다(고신뢰면 전용 핸들러로 바로 가므로 불필요).
        # 아래 두 가드가 이 값을 공유한다 — Qdrant 왕복을 한 번으로 묶기 위함.
        doc_count = None
        if score < _HIGH_CONFIDENCE and topic_name:
            try:
                doc_count = await loop.run_in_executor(
                    None, rag_service.vector_store.count_by_topic, topic_name
                )
            except Exception as e:
                print(f"[Graph] topic 문서 수 확인 실패 (가드 생략, 그대로 진행): {e}")

        # 새 topic에 문서가 하나도 없으면 전환 취소 → 이전 topic 유지
        # (빈 topic 전환 → 검색 0건 → 환각 답변으로 이어지는 함정 방지)
        # RAG 핸들러로의 전환만 검사 — graduation/campus/scholarship/general(chitchat 포함)은
        # Qdrant 문서가 아닌 DB 조회/코드 파싱/전용 로직으로 답하므로 문서 개수가 무의미함
        # 단, 새 분류가 확신(score >= _HIGH_CONFIDENCE)이면 전환한다 — 사용자가 명확히 새
        # topic을 물었으면, 빈 topic이어도 RAG가 "자료 없음"을 정직히 답하는 게(0건 fallback)
        # 엉뚱한 이전 topic 답변보다 낫다. 이전 topic도 비어있을 때 계속 갇히는 버그 방지.
        if doc_count == 0 and prev_topic and topic_name != prev_topic and handler_type == "rag":
            prev_handler, prev_route_topic = _resolve_prev_route(prev_topic)
            if prev_handler:
                print(f"[Graph] '{topic_name}' 문서 0개 → 전환 취소, 이전 topic '{prev_topic}' 유지 (handler={prev_handler})")
                return {"intent": prev_handler, "topic": prev_route_topic, "confidence": score}

        # 저신뢰 폴백인데 topic에 문서가 없으면 필터를 풀어 전체 검색으로 보낸다.
        # 필터를 남겨 두면 문서 0개인 topic(dining·schedule·campus처럼 전용 핸들러가 DB·캐시로
        # 답하는 토픽)을 뒤지게 돼 검색이 무조건 0건 → "자료를 찾지 못했어요"로 끝나는 막다른 길이다.
        # 실측: '동캠 밥 뭐나와' → dining 0.558 → topic=dining으로 검색 → 0건,
        #       '동캠퍼스는뭐나와' → campus 0.548 → topic=campus로 검색 → 0건.
        # _route_embedding의 폴백 취지가 '토픽 필터 없는 전체 검색'이므로 여기서 실제로 풀어 준다.
        if doc_count == 0:
            print(f"[Graph] 저신뢰({score:.3f}) + '{topic_name}' 문서 0개 → topic 필터 해제, 전체 검색")
            return {"intent": handler_type, "topic": None, "confidence": score,
                    "topic_no_docs": True}

        return {"intent": handler_type, "topic": topic_name, "confidence": score,
                "topic_no_docs": False}
    except Exception as e:
        print(f"[Graph] 임베딩 분류 실패: {e}")
        return {"intent": None, "topic": None, "confidence": 0.0}



# ── 개인 시간표: 검색으로 답이 나올 수 없는 질문 ────────────────────────
# 시간표는 학생마다 달라 코퍼스에 있을 수 없다(실측: '시간표'가 든 청크는 기숙사 간사
# 근무표와 시험시간표 공고 규정 둘뿐, 개인 강의시간표는 없음). 그런데 검색을 태우면
# 리라이트가 '오늘 수업 뭐 있어?'를 '수업 일정'으로 바꾸면서 '오늘'을 버리고, 그러면
# 솔숲 신입생 OT 표가 리랭커 0.585로 잡혀(임계 0.4 통과) 근거 확인을 빠져나간다.
# 결과: "오늘 수업은 오전 09:00~12:00 프로그램 안내…"라는 완전한 거짓말(실측).
# 근거 약함이 아니라 '확신에 찬 오답'이라 점수 기반 가드로는 못 막는다 → 검색 자체를 생략한다.
_TIMETABLE_WORDS = ("시간표", "수업", "강의")
# 날짜어를 반드시 함께 요구한다. 안 그러면 '어학센터 수업 있어?'(프로그램 문의)와
# 'S3 강의실 찾고 있어요'(위치)까지 막힌다 — 실제 대화기록에서 확인한 오탐이다.
_TIMETABLE_DATE = ("오늘", "내일", "모레", "이번주", "다음주",
                   "월요일", "화요일", "수요일", "목요일", "금요일")
# '강의실'은 위치, '셔틀'은 운행표, '시험시간표'·'강의계획서'는 공지 대상이다.
_TIMETABLE_EXCLUDE = ("강의실", "셔틀", "버스", "시험시간표", "강의계획서")


def _is_personal_timetable(question: str) -> bool:
    """개인 시간표를 묻는가 — 실제 질문 2,142건 기준 3건만 잡히고 오탐 0건."""
    compact = (question or "").replace(" ", "")
    if any(x in compact for x in _TIMETABLE_EXCLUDE):
        return False
    return (any(w in compact for w in _TIMETABLE_WORDS)
            and any(d in compact for d in _TIMETABLE_DATE))


# ── 내 성적 조회: 문서가 아니라 학생 본인의 수강 이력이 답인 질문 ──────────
# grades 토픽엔 성적 '제도' 문서(이의신청·학점포기·학사경고)만 있어서, '2학년 1학기 성적
# 알려줘'를 검색에 태우면 제도 문서를 근거로 엉뚱한 답을 만든다. 개인 데이터가 답인 질문은
# 검색 전에 갈라 전용 핸들러로 보낸다(개인 시간표 게이트와 같은 원리 — 다만 이쪽은 답이 있다).
# 판정 규칙 자체는 services/school/my_grades.py에 모아 두었다(파일 상단에서 import) —
# 핸들러의 재검증(looks_personal)과 같은 규칙을 써야, 한쪽만 고쳐 두 판정이 어긋나지 않는다.


async def _keyword_classify(state: AgentState) -> dict:
    """규칙 기반 fast-path 분류 (0ms) — campus 건물코드 / 학사일정 날짜질문 / 개인 시간표"""
    if _is_campus_question(state["question"]):
        print("[Graph] 키워드 분류 → campus")
        return {"intent": "campus"}
    # 건물명이 DB에 매칭되고, 위치 의도가 있거나(→위치) '정보·절차 의도가 없으면'(건물명만 침) campus.
    #   '동캠학생회관'·'학군단 어디' → campus / '학군단 뭐야'·'학군단 모집 언제' → RAG로 넘김.
    # (regex 먼저 걸러 대부분의 질문은 DB 조회 없이 통과 — 정보의도어가 있으면 즉시 skip)
    q = state["question"]
    if not _PROCEDURE_RE.search(q) and await _campus_gate(q):
        print("[Graph] 키워드 분류 → campus (건물명 매칭)")
        return {"intent": "campus"}
    # 학사일정 날짜 질문보다 먼저 본다 — '오늘 수업 뭐 있어?'는 날짜어가 있어 그쪽에
    # 먼저 걸리고, 학사일정에 없으니 결국 전체 검색 폴백으로 새기 때문이다.
    # campus 판정 뒤에 두어 'S3 강의실 찾고 있어요' 같은 위치 질문은 campus가 먼저 가져간다.
    if _is_personal_timetable(state["question"]):
        print("[Graph] 키워드 분류 → 개인 시간표(시스템에 없는 데이터)")
        return {"intent": "no_data"}
    if _is_schedule_date_question(state["question"]):
        print("[Graph] 키워드 분류 → schedule (날짜 질문 fast-path)")
        return {"intent": "schedule", "topic": "schedule"}
    # 학사일정보다 뒤에 둔다 — '성적 언제 나와?'는 날짜 질문이라 달력이 답이고,
    # '2학년 1학기 성적 알려줘'는 날짜 의도어가 없어 위 게이트에 걸리지 않는다.
    if _is_my_grades_question(state["question"]):
        print("[Graph] 키워드 분류 → my_grades (본인 수강 이력 조회)")
        return {"intent": "my_grades", "topic": "my_grades"}
    _prev = state.get("prev_context") or {}
    if _prev.get("prev_topic") == "my_grades" and _is_grade_fragment(state["question"]):
        print("[Graph] 키워드 분류 → my_grades (직전 성적 조회의 학기 후속)")
        return {"intent": "my_grades", "topic": "my_grades"}
    return {"intent": None}


# 주소는 '수강신청_매뉴얼(한국어)' 문서에 적힌 실제 경로다("대학정보시스템 로그인
# (https://wsinfo.wsu.ac.kr)"). 학교가 주소를 바꾸면 이 줄도 같이 고쳐야 한다.
_NO_TIMETABLE_REPLY = (
    "개인 시간표는 코파일럿에서 확인할 수 없어요. "
    "대학정보시스템(https://wsinfo.wsu.ac.kr)에서 확인해 주세요."
)


async def _handle_no_data(state: AgentState) -> dict:
    """코퍼스에 있을 수 없는 개인 데이터 질문 — 검색도 LLM도 타지 않는다.

    검색을 태우면 리랭커가 '수업 일정'처럼 생긴 아무 표나 자신 있게 집어 오고, 그걸로
    LLM이 오늘 시간표를 지어낸다(실측 0.585). 답이 있을 수 없는 질문이므로 아예 묻지 않는다.
    """
    print("[Graph] 개인 데이터 질문 → 검색 생략, 안내 응답")
    return {
        "answer": _NO_TIMETABLE_REPLY,
        "source": None,
        "source_file": None,
        "topic": None,
    }


# 위치를 묻는 신호. 위치 검색이 실패했을 때 '건물명을 다시 입력해 달라'는 안내를
# 내보내도 되는지 가른다.
_LOCATION_INTENT = ("어디", "위치", "찾아가", "가는 법", "가는길", "가는 길",
                    "몇 층", "몇층", "층에", "어느 건물", "어떻게 가")


async def _handle_campus(state: AgentState) -> dict:
    await _log(state["db"], state["student_id"], "campus")
    result = await _campus_service.search_location(state["question"])
    # 위치를 못 찾았을 때는 두 경우를 갈라야 한다.
    #  (1) 진짜 위치 질문인데 건물명을 못 알아들음 → 건물명을 다시 물어보는 안내가 맞다.
    #  (2) 위치 질문이 아닌데 라우터가 campus로 보냄 → 그 안내가 질문과 동떨어져 혼란만 준다.
    #      실측: '우송대는 어떤 학교야?'(campus 0.719) → "건물명, 학과명, 강의실 번호를
    #      조금 더 정확하게 입력해주세요"가 나갔다. 학교 소개를 물었는데 건물명을 되묻는 꼴이다.
    # (2)는 dining이 쓰는 폴백과 같은 처리를 한다 — 전체 검색으로 한 번 더 찾아보되
    # 근거가 약하면 답을 만들지 않고 '못 찾음'으로 끝낸다(검수 FAQ가 있으면 그게 이긴다).
    if not result.get("found"):
        q = state.get("question", "")
        if not any(k in q for k in _LOCATION_INTENT):
            return await _rag_fallback_guarded(state, "위치 질문 아님")
    return {
        "answer": result.get("answer", "위치 정보를 찾을 수 없습니다."),
        "map_card": result.get("map_card") if result.get("found") else None,
        "source": result.get("source") or (result.get("map_card") or {}).get("source"),
        "source_file": None,
        "topic": "campus",
    }


# ── 게스트(비로그인) 안내 ────────────────────────────────────────────────
# 개인 데이터가 있어야 답할 수 있는 질문에 쓴다. "안 됩니다"로 끝내지 않고
# 로그인하면 무엇을 받을 수 있는지 알려 준다 — 막다른 길을 만들지 않는다는 원칙은
# 게스트에게도 같다. login_required는 프론트가 로그인 버튼을 붙이는 신호다.
def _login_required(what: str, topic: str) -> dict:
    return {
        "answer": (
            f"{what}은(는) 로그인한 학생의 학번·학과 정보를 기준으로 계산해서 알려드려요.\n\n"
            "**로그인하시면 바로 확인하실 수 있습니다.**\n\n"
            "로그인 없이도 학사 규정, 학사일정, 학식, 캠퍼스 위치, 학과 안내, "
            "각종 신청서 서식은 그대로 이용하실 수 있어요."
        ),
        "source": None,
        "source_file": None,
        "topic": topic,
        "login_required": True,
    }


async def _handle_my_grades(state: AgentState) -> dict:
    """내 성적 조회 — 마이페이지에 올린 수강 이력(DB)으로 직접 답한다. RAG도 LLM도 안 탄다.

    성적 '제도'를 묻는 질문(학점포기·이의신청·학사경고)이 라우터를 통해 여기로 올 수 있다.
    개인 이력으로는 답할 수 없는 질문이므로 grades 토픽 RAG로 넘긴다 — 막다른 길을 만들지 않는다.
    학기 파싱은 '현재 질문' 기준이다. 다만 '1학년 1학기 성적' 뒤의 '2학기는?'처럼 학년이
    생략된 후속은 기준을 잃으므로, 직전에도 성적을 물었을 때만 이전 질문을 함께 넘겨
    학년(또는 년도)을 빌려 쓰게 한다. 직전 주제가 다르면 넘기지 않는다 — 무관한 질문의
    학년이 섞이면 묻지 않은 학기를 답한다(graduation·schedule과 같은 이유).
    """
    # 게스트는 올린 수강 이력이 없다 — 여기서 막지 않으면 빈 이력으로 "기록이 없다"는
    # 답이 나가, 로그인만 하면 되는 상황인데 기능 자체가 없는 것처럼 읽힌다.
    if state.get("student_id") is None:
        return _login_required("성적과 수강 이력", "my_grades")

    _prev = state.get("prev_context") or {}
    prev_topic = _prev.get("prev_topic")
    prev_q = _prev.get("prev_question") if prev_topic == "my_grades" else None
    answer, meta = await my_grades_service.answer(
        question=state["question"], student_id=state["student_id"], db=state["db"],
        prev_question=prev_q, prev_topic=prev_topic,
    )
    if meta.get("fallback"):
        # 성적 규정 문서는 grades 토픽에 있다 — 전체 검색으로 풀지 않고 그 토픽으로 좁혀 넘긴다.
        print(f"[Graph] my_grades → RAG 폴백: {meta['fallback']}")
        return await _handle_rag_general({**state, "topic": "grades"})
    await _log(state["db"], state["student_id"], "my_grades")
    return {
        "answer": answer,
        "source": meta.get("source"),
        "source_file": None,
        "topic": "my_grades",
    }


async def _handle_department(state: AgentState) -> dict:
    """학과/학부/단과대 안내 — DB 조회(RAG 미사용). 상세 소개는 홈페이지 링크로 넘긴다."""
    await _log(state["db"], state["student_id"], "college_department")
    # 학과 탐지는 '현재 질문' 기준이어야 한다. 이전 주제 프리픽스를 섞으면 "간호학과 어디야"
    # 뒤의 "컴공은?"에서 프리픽스의 간호학과가 더 긴 매칭으로 이겨버린다 (graduation과 동일 원칙).
    result = await answer_department_question(state["question"], state["db"])
    return {
        "answer": result["answer"],
        "dept_card": result["dept_card"],
        "source": "database",
        "source_file": None,
        "topic": "college_department",
    }


# 답을 지어내느니 모른다고 하는 쪽이 낫다고 판단했을 때의 문구.
# rag_general이 검색 0건일 때 쓰는 안내와 같은 말로 맞춰 사용자 눈에 일관되게 보이게 한다.
_NOT_FOUND_REPLY = (
    "죄송해요, 해당 내용에 대한 자료를 찾지 못했어요. "
    "조금 더 구체적으로 질문해 주시거나, "
    "학교 공식 홈페이지(wsu.ac.kr) 또는 담당 부서에 문의해 주세요."
)


async def _faq_for_non_dining(question: str) -> dict | None:
    """학식 질문이 아니라고 걸러진 질문을 검수 FAQ로 먼저 받아본다. 없으면 None.

    라우터가 dining으로 보낸 질문 중에는 검수된 답이 이미 있는 것들이 섞여 있는데,
    그동안 학식 담당이 가로채서 FAQ까지 닿지 못했다 — 실측: '맛집 추천해줘'는 FAQ에
    교외 맛집 10곳이 등록돼 있는데도 학식 메뉴가 나갔다(FAQ 유사도 1.000).
    '과사 점심시간 언제야?'도 마찬가지(1.000).

    LLM을 건너뛰고 그대로 내보내는 경로라 오매칭이 곧 확정 오답이다. 그래서 일반 조회
    (0.70)가 아니라 엄격 임계값을 쓴다 — rag_general·graduation의 verbatim 경로와 같은 기준.
    """
    loop = asyncio.get_event_loop()
    from app.services.faq_index import faq_lookup, FAQ_STRICT_THRESHOLD
    hit = await loop.run_in_executor(None, faq_lookup, question, FAQ_STRICT_THRESHOLD)
    if not hit:
        return None
    print(f"[Graph] 학식 아님 + FAQ 매칭({hit[1]:.3f}) → verbatim 답변")
    return {"answer": hit[0], "source": "faq", "source_file": None, "topic": "general"}


async def _rag_fallback_guarded(state: AgentState, why: str) -> dict:
    """오라우팅된 질문의 전체 검색 폴백 — 근거가 약하면 답을 만들지 않는다.

    dining·schedule 토픽엔 Qdrant 문서가 0개라, 이 폴백은 항상 topic 없이 전 문서를 뒤진다.
    그런데 라우터가 잘못 보낸 질문은 제 주제의 문서가 애초에 코퍼스에 없다. 리트리버는
    '못 찾음'을 피하려고 어휘가 겹치는 문서를 살려 주는데(retriever.py 3-1b), 그 구제는
    청크가 아니라 '문서' 단위라 정작 넘어가는 청크엔 그 단어가 없을 수도 있다.
    실측 — '오늘 수업 뭐 있어?': 내용어는 '오늘'(0건)·'수업'(7건)뿐인데, '수업'이 든 다른
    청크 때문에 솔숲 문서가 열려 신입생 OT 시간표가 넘어갔고 LLM이 오늘 시간표로 답했다.
    같은 원인으로 '축제언제야?'는 그 OT 일정을 축제로, '오늘 공지 뭐 올라왔어?'는 5월
    근로장학 공고를 오늘 공지로 답했다(셋 다 리랭크 최고점 0.000).

    rag_general은 이 상태에서 먼저 검수 FAQ를 조회하므로(0.75), 검수된 답이 있으면
    source='faq'로 돌아온다 — 그건 그대로 내보낸다. 근거가 확실한 폴백도 마찬가지다
    (실측: '기숙사 통금' 0.815, '도서 대출 몇 권' 등 리랭커 저점수 정답은 죽지 않는다).
    """
    print(f"[Graph] {why} → RAG 폴백")
    result = await _handle_rag_general({**state, "topic": None})
    if result.get("weak_evidence") and result.get("source") != "faq":
        print(f"[Graph] {why} + 검색 근거도 약함 → 답변 생성 대신 '못 찾음'")
        return {
            "answer": _NOT_FOUND_REPLY,
            "source": None,
            "source_file": None,
            "topic": None,
        }
    return result


async def _handle_dining(state: AgentState) -> dict:
    """학식 안내(메뉴·위치·운영시간·전화·가격) — RAG도 LLM도 타지 않는다.

    주간 식단은 매주 바뀌는 휘발성 데이터라 Qdrant에 넣지 않기로 한 설계다(주 단위 캐시를
    직접 조회). answer_dining_question이 완성된 문자열을 돌려주므로 여기선 그대로 싣는다.

    질문은 '현재 질문'을 그대로 넘긴다 — 이전 주제를 앞에 이어 붙이면 "동캠 학식" 뒤의
    "서캠은?"에서 두 식당명이 다 잡혀 엉뚱한 쪽이 이긴다(graduation·schedule과 동일 원칙).
    직전 질문은 별도 인자로 줘서, 현재 질문에 식당명이 없을 때만 보충하게 한다
    ("기숙사 식당 밥 뭐야" → "가격은?"이 서캠 가격으로 답하던 문제).
    """
    await _log(state["db"], state["student_id"], "dining")
    prev = state.get("prev_context")
    answer, found = await answer_dining_question_with_meta(
        state["question"],
        prev_question=prev.get("prev_question") if prev else None,
    )
    # 학교 식당안내 표의 칸이 비어 있어도 다른 문서에 답이 있을 수 있다 —
    # '기숙사 식당 가격'은 이 표엔 '-'지만 기숙사비_안내 문서에 식비 내역(1일 4,000원)이 있다.
    # 여기서 끝내면 막다른 길이 되므로 RAG로 넘긴다(_handle_schedule의 0건 폴백과 동일 패턴).
    # topic은 비워 전체 검색으로 돌린다 — dining 토픽엔 Qdrant 문서가 없다.
    if not found:
        # 빈 답변 = _looks_like_dining이 '학식 질문이 아니다'라고 막은 경우.
        # 안내표 칸이 비어서 온 경우는 안내 문구가 들어 있어 구분된다.
        gate_blocked = not answer
        if gate_blocked:
            # 검수된 답이 이미 있는 질문이면 RAG보다 그게 정확하다(맛집·과사 운영시간 등).
            hit = await _faq_for_non_dining(state["question"])
            if hit is not None:
                return hit
            return await _rag_fallback_guarded(state, "학식 질문 아님")
        # 안내표 칸만 비어 있는 경우는 진짜 학식 질문이라 근거 확인을 걸지 않는다 —
        # '기숙사 식당 가격'처럼 다른 문서(기숙사비_안내)에 답이 흩어져 있을 수 있다.
        print("[Graph] 학식 안내표에 값 없음 → RAG 폴백")
        return await _handle_rag_general({**state, "topic": None})
    return {
        "answer": answer,
        "source": "dining",
        "source_file": None,
        "topic": "dining",
    }


async def _handle_weather(state: AgentState) -> dict:
    """캠퍼스 날씨 — 외부 API(OpenWeatherMap) 직접 조회.

    학식(dining)과 달리 실패해도 RAG로 넘기지 않는다. 날씨는 학사 문서에 없는 데이터라
    RAG로 내려보내도 답이 나올 수 없고, 오히려 무관한 문서를 근거로 그럴듯한 오답을
    만들 위험만 생긴다(근거약함 게이트가 엉뚱한 FAQ를 물어온 전례가 있다).
    → 서비스가 만든 안내 문구를 그대로 내보내고 거기서 끝낸다.

    LLM을 태우지 않는 것도 같은 이유다. 기온·강수확률은 숫자를 그대로 보여 주는 것이
    가장 정확하고, 문장을 다시 만들게 하면 실행할 때마다 표현이 흔들리고 값이 바뀔 여지가
    생긴다(졸업요건을 temperature=0으로 고정한 것과 같은 판단).
    """
    from app.services.school.weather import answer_weather_question, build_weather_card

    await _log(state["db"], state["student_id"], "weather")
    answer, ok = answer_weather_question(state["question"])
    if not ok:
        print("[Graph] 날씨 조회 실패 → 안내 문구로 종료(RAG 폴백 없음)")
        return {"answer": answer, "source": "weather", "source_file": None, "topic": "weather"}
    # 카드는 덧붙이는 것이라 실패해도 답변에는 영향이 없다(build_weather_card가 None을 준다).
    return {
        "answer": answer,
        "source": "weather",
        "source_file": None,
        "topic": "weather",
        "weather_card": build_weather_card(),
    }


async def _handle_graduation(state: AgentState) -> dict:
    await _log(state["db"], state["student_id"], "graduation")

    # 게스트: 개인 판정은 못 하지만 졸업 '규정'과 '학과별 요건'은 답할 수 있다.
    # 요건은 학과×입학연도 기준이라 본인 이수현황이 필요 없고, graduation_service가
    # 학생 레코드 없는 호출을 이미 처리한다(학과 감지 → requirement_set 조회 →
    # 연도 미언급 시 그 학과 최신 연도). 그래서 로그인 사용자와 같은 경로로 보낸다.
    #
    # 예전에는 여기서 곧장 RAG로 내려보냈는데, 그러면 학과 별칭 해석과 학점 표 조회를
    # 통째로 건너뛴다. 학점 표는 문서가 아니라 DB(requirement_rule)에 있어 RAG로는
    # 닿지 못한다 — 실측: 로그인 시 정상 인식되는 '컴퓨터정보보안학과 졸업요건'이
    # 비로그인에서는 "정보가 명시되어 있지 않습니다"로 나갔다.
    is_guest = state.get("student_id") is None

    # 졸업 분기(학과 감지·유형 분류)는 반드시 '현재 질문' 기준이어야 한다.
    # enriched(이전 주제 프리픽스)를 넘기면 "간호학과 졸업요건" 뒤 "내 학과 졸업요건"이
    # 프리픽스의 '간호학과'를 학과로 오인 → 다른 학과 요건이 나오는 치명적 버그.
    answer, metadata = await graduation_service.answer_graduation_with_metadata(
        question=state["question"], student_id=state["student_id"], db=state["db"]
    )
    answer = _append_contact_info(answer, metadata)
    if is_guest:
        # 답은 그대로 주고, 개인 기준 계산이 더 있다는 것만 덧붙인다.
        answer = answer.rstrip() + (
            "\n\n---\n\n🔒 **로그인하시면 본인의 학번·학과 기준으로 "
            "남은 학점과 부족한 요건까지 계산해서 알려드려요.**"
        )
    out = _with_file_offer({
        "answer": answer,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": metadata.get("topic") or "graduation",
    }, "graduation", state["question"])
    if is_guest:
        out["login_required"] = True
    return out


# 달력은 '언제'를 묻는 질문에만 답이 된다. 이벤트어(계절학기·공휴일 등)가 들어 있다는 이유로
# 달력을 내보내면, 그 일정의 '성격'을 묻는 질문에 날짜표가 나간다 — 실측: '계절학기 들어야 해?'에
# 겨울학기 수강신청 기간 7행이 나갔다. 학사일정 핸들러는 검색을 안 타므로 FAQ에도 닿지 못한다.
# 실제 질문 2,157종 전수: 핸들러 도달 189종 / 달력이 답을 내던 130종 중 여기 걸리는 건 8종뿐이고
# (계절학기 6 + '과사 공휴일에 해?' 2), 8종 모두 검수된 FAQ 답이 0.88 이상으로 이미 있다.
_TIMING_WORDS = (
    "언제", "며칠", "몇월", "몇일", "몇시", "날짜", "요일",
    "기간", "일정", "스케줄", "달력", "마감", "데드라인",
    "시작", "끝", "종료", "개강", "종강", "개학", "남았", "남은",
    "오늘", "내일", "모레", "이번주", "다음주", "이번달", "다음달",
    "부터", "까지", "전에", "이후",
)


def _asks_about_timing(question: str) -> bool:
    """일정의 '시점'을 묻는 질문인가 — 아니면 달력을 답으로 쓰지 않는다."""
    return any(w in (question or "").replace(" ", "") for w in _TIMING_WORDS)


async def _handle_schedule(state: AgentState) -> dict:
    await _log(state["db"], state["student_id"], "schedule")
    # 학사일정 분기(날짜·이벤트 파싱)는 '현재 질문' 기준으로만 해야 한다. 이전 주제 프리픽스를
    # 넣으면 엉뚱한 이벤트/날짜로 오인될 수 있어 원 질문만 넘긴다(graduation과 동일 원칙).
    answer, metadata = await schedule_service.answer_schedule_with_metadata(
        question=state["question"], db=state["db"]
    )
    # 매칭 0건 = 라우팅이 잘못 왔거나 학사일정에 없는 내용. 여기서 끝내면 막다른 길이 되므로
    # RAG로 넘긴다. topic은 비워서(schedule 토픽엔 문서가 없다) 전체 검색으로 돌린다.
    if metadata.get("no_match"):
        return await _rag_fallback_guarded(state, "학사일정 매칭 0건")
    # '시간표'는 날짜가 아니라 문서 이름이라 달력에 있을 수 없다. 언제 공고되는지는 성적평가
    # 및 처리규정 제3조("학기말시험의 시험시간표는 시험개시 일주일전에 공고한다")에 적혀 있어
    # 검색으로 답이 나온다 — 실측: '시험시간표 어디서 봐?'가 그 조문을 그대로 답한다.
    # 달력을 두면 '시험시간표 언제 나와?'에 시험 기간이 나가 묻지 않은 걸 답한다(실측).
    # ('시간표'가 든 실제 질문은 3종뿐이고 달력이 답을 내던 건 이 1종이다.)
    if "시간표" in state["question"].replace(" ", ""):
        return await _rag_fallback_guarded(state, "시간표는 달력에 없는 문서")
    # 달력에 맞는 행이 있어도, 질문이 시점을 묻는 게 아니면 그건 답이 아니다(위 주석 참조).
    if not _asks_about_timing(state["question"]):
        return await _rag_fallback_guarded(state, "일정의 시점을 묻는 질문이 아님")

    answer = _append_contact_info(answer, metadata)
    return {
        "answer": answer,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": metadata.get("topic") or "schedule",
        "schedule_card": metadata.get("schedule_card"),
    }


# 국가장학금 검수 Q&A는 Qdrant(topic=scholarship_faq)에 '질문 임베딩 + 답변 원문'으로 저장돼 있다.
# (관리: RAG 지식 목록, source='국가장학금 FAQ'). 질문으로 검색해 코사인 ≥ 임계값이면 답변을 '그대로'
# 반환한다 — LLM을 안 거쳐 숫자(소득구간·성적 기준 등)가 변형되지 않는다.
_SCHOLARSHIP_ABBR = {"국장": "국가장학금"}   # 학생 약어 → 정식 명칭 (매칭률↑)
_SCHOLARSHIP_FAQ_THRESHOLD = 0.81

# '목록·추천·내 자격'을 묻는 질문은 검수 FAQ의 몫이 아니다 — 맞춤 설문과 카테고리 카드가 답이다.
# 문제: '장학금'이라는 단어가 임베딩을 지배해서, 무슨 장학금이 있냐고 물어도 국가장학금 '정의'
# FAQ가 0.82~0.87로 걸린다. 그래서 서로 다른 질문에 똑같은 정의 문단이 나갔다(실측:
# '국가장학금 추천해줘' 0.870 / '장학금 뭐 있어?' 0.853 / '내가 받을 수 있는 장학금' 0.835 —
# 셋 다 같은 답). 임계값을 올려 막으려면 0.88 이상이어야 하는데 그러면 정상 매칭까지 죽는다.
# → 점수가 아니라 '질문의 성격'으로 가른다. 목록·추천 의도어가 있으면 FAQ를 건너뛴다.
_SCHOLARSHIP_BROWSE_RE = re.compile(
    r"추천|뭐\s*있|뭐가\s*있|무엇이\s*있|어떤\s*게?\s*있|어떤\s*것?\s*있|종류|목록|"
    r"받을\s*수\s*있|받을수있|내가\s*받|나\s*받|찾아\s*줘|찾아줘"
)


def _is_scholarship_browse(question: str) -> bool:
    """장학금 '목록·추천' 질문인가 — 검수 FAQ 대신 맞춤 설문·카테고리 카드로 보낼 질문."""
    return bool(_SCHOLARSHIP_BROWSE_RE.search(question or ""))


def _lookup_scholarship_faq(question: str) -> str | None:
    q = question
    for _abbr, _full in _SCHOLARSHIP_ABBR.items():
        if _abbr in q:
            q = q.replace(_abbr, _full)
    try:
        qv = rag_service.embedding.embed_text(q)
        results = rag_service.vector_store.search(qv, topic="scholarship_faq", limit=1)
    except Exception as e:
        print(f"[Scholarship FAQ] 조회 실패(무시): {e}")
        return None
    if results and results[0].score >= _SCHOLARSHIP_FAQ_THRESHOLD:
        print(f"[Scholarship FAQ] 매칭 {results[0].score:.3f} ≥ {_SCHOLARSHIP_FAQ_THRESHOLD} → 원문 답변")
        return results[0].text
    return None


async def _handle_scholarship(state: AgentState) -> dict:
    """장학금 질문 처리:
      1) Qdrant 검수 Q&A(국가장학금)에 매칭되면 저장된 답변을 그대로 반환(LLM 미사용 = 숫자 안 틀림)
      2) 없으면 안내문 + '맞춤 설문' 제안(예/아니오) — 프론트가 scholarship_card={'survey':True}로 렌더
    """
    await _log(state["db"], state["student_id"], "scholarship")
    # 1) 검수 Q&A 우선 (질문 임베딩 → Qdrant 코사인 검색 → 원문 답변)
    #    단 '목록·추천' 질문은 건너뛴다 — 정의 FAQ가 0.85 안팎으로 걸려 설문 제안을 가로챈다.
    loop = asyncio.get_event_loop()
    verbatim = None
    if not _is_scholarship_browse(state["question"]):
        verbatim = await loop.run_in_executor(None, _lookup_scholarship_faq, state["question"])
    if verbatim:
        return {
            "answer": verbatim,
            "next_pending_context": None,
            "source": "scholarship_faq",
            "source_file": None,
            "topic": "scholarship",
        }
    # 2) 매칭 없으면 맞춤 설문 제안
    #    게스트에게는 설문을 제안하지 않는다 — 설문 결과를 거를 학번·학과·학점이 없고,
    #    제안을 눌러도 장학금 API가 로그인을 요구해 막다른 길이 된다.
    #    검수 Q&A(위 1번)는 개인 정보와 무관하므로 게스트도 그대로 받는다.
    if state.get("student_id") is None:
        return _login_required("나에게 맞는 장학금 추천", "scholarship")

    answer = (
        "장학금 종류나 찾으시는 장학금은 사이드바의 ‘장학금 둘러보기’에서 "
        "전체 목록을 확인하실 수 있어요.\n\n"
        "간단한 설문으로 **나에게 맞는 장학금**을 찾아드릴 수도 있어요. 확인해 드릴까요?"
    )
    return {
        "answer": answer,
        "next_pending_context": None,
        "source": None,
        "source_file": None,
        "topic": "scholarship",
        "scholarship_card": {"survey": True},   # 프론트: 설문 제안(예/아니오) 렌더 신호
    }


# 근로장학 검수 Q&A도 국가장학금과 같은 방식(topic=work_study_faq)으로 Qdrant에 저장돼 있다.
# work_study는 전용 핸들러가 없고 rag로 라우팅되므로, RAG 검색 전에 여기서 먼저 조회한다.
# 0.81은 낮았다 — '근로장학 하면 수업 빠져도 돼?'가 0.813으로 휴학 답변을 채택했다(확정 오답).
# 그 질문은 상위 3개가 0.813/0.798/0.793으로 평평했다 = 정답이 없다는 신호.
# 실측 19문항: 0.81 → 정답 9/11·오답 3/8, 0.85 → 정답 8/11·오답 0/8.
# verbatim 경로는 LLM을 안 거쳐 오매칭이 곧 확정 오답이라, '놓침'보다 '틀린 답'이 훨씬 비싸다.
_WORK_STUDY_FAQ_THRESHOLD = 0.85


# 라우팅이 work_study가 아닐 때 쓰는 상향 임계값. 근로 질문은 '근무지는 내가 정해?'처럼
# 토픽 프로토타입과 어휘가 안 겹쳐 welfare_facilities·drop_out 등으로 오분류되는 일이 잦다.
# (rewrite가 '근무지' 같은 핵심어를 떨어뜨려 라우팅을 흔드는 경우도 있다.)
# 그래서 rag 계열 토픽이면 어디로 갔든 검수 Q&A를 조회하되, 라우팅이 동의하지 않을 땐
# 더 확실할 때만(0.88) 채택해 다른 토픽 질문을 가로채지 않게 한다.
_WORK_STUDY_FAQ_STRICT = 0.88


def _lookup_work_study_faq(question: str, threshold: float | None = None) -> str | None:
    th = _WORK_STUDY_FAQ_THRESHOLD if threshold is None else threshold
    try:
        qv = rag_service.embedding.embed_text(question)
        results = rag_service.vector_store.search(qv, topic="work_study_faq", limit=1)
    except Exception as e:
        print(f"[WorkStudy FAQ] 조회 실패(무시): {e}")
        return None
    if results and results[0].score >= th:
        print(f"[WorkStudy FAQ] 매칭 {results[0].score:.3f} ≥ {th} → 원문 답변")
        return results[0].text
    return None


async def _handle_rag_general(state: AgentState) -> dict:
    """RAG 검색 핸들러 — state["topic"]을 Qdrant 필터로 사용 (None이면 필터 없이 전체 검색)"""
    # topic=None은 '전체 검색' 의도다(학사일정 0건 폴백, 저신뢰 폴백 등). 여기서 "rag_general"로
    # 메우면 실재하는 '일반학사' 토픽으로 필터링돼 의도와 정반대가 된다 — 전체 검색인 줄 알았던
    # 폴백들이 실제로는 좁게 검색하고 있었다. 기본값은 로그 라벨에만 쓴다.
    topic = state.get("topic")

    # 근로장학 검수 Q&A를 RAG 검색보다 먼저 조회 — 매칭되면 LLM 없이 원문 그대로(숫자·조건 변형 방지).
    # 라우팅이 work_study가 아니어도 조회하되(오분류 구제), 그때는 상향 임계값을 적용한다.
    # 검색은 rewrite된 문장이 아니라 학생이 실제로 친 원문(state["question"])으로 한다.
    # _log는 이 조회 뒤에 한다 — 적중 시 실제로 답한 토픽(work_study)을 기록해야 통계가 안 어긋난다.
    _th = _WORK_STUDY_FAQ_THRESHOLD if topic == "work_study" else _WORK_STUDY_FAQ_STRICT
    loop = asyncio.get_event_loop()
    verbatim = await loop.run_in_executor(None, _lookup_work_study_faq, state["question"], _th)
    if verbatim:
        await _log(state["db"], state["student_id"], "work_study")
        return {
            "answer": verbatim,
            "next_pending_context": None,
            "source": "work_study_faq",
            "source_file": None,
            "topic": "work_study",
        }

    await _log(state["db"], state["student_id"], topic or "rag_general")

    prev_prefix = _build_prev_prefix(state)
    enriched_question = prev_prefix + state["question"] if prev_prefix else None

    # prev_prefix가 있다 = topic 유지된 후속 질문 → rewrite에도 이전 질문 맥락 전달
    prev = state.get("prev_context")
    # 지금: topic 유지된 후속일 때만 이전 질문 전달
    prev_question = prev.get("prev_question") if (prev_prefix and prev) else None
    # A 전환: 이전 대화만 있으면 항상 전달
    #prev_question = prev.get("prev_question") if prev else None

    answer, metadata = await answer_rag_general_question_with_metadata(
        state["question"],          # 검색/rewrite용 원본 질문
        topic=topic,
        context_question=enriched_question,  # LLM 맥락용 (이전 주제 힌트 포함)
        prev_question=prev_question,         # 후속 질문이면 rewrite에 맥락 통합
        search_query=state.get("search_query"),  # rewrite 노드가 이미 재작성했으면 재사용(이중 rewrite 방지)
        db=state["db"],                          # 날짜 질문이면 학사일정을 컨텍스트에 보강
    )
    answer = _append_contact_info(answer, metadata)
    return _with_file_offer({
        "answer": answer,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": metadata.get("topic") or topic,
        "rewritten_query": metadata.get("rewritten_query"),
        "files_to_offer": metadata.get("files_to_offer", []),
        "schedule_card": metadata.get("schedule_card"),   # 보강으로 붙은 미니 달력
        # 리랭커가 다 떨어뜨린 걸 어휘 매칭으로 겨우 건진 상태. 폴백으로 여기 들어온
        # 호출부가 '이 답을 내보내도 되는지' 판단할 수 있게 그대로 실어 보낸다.
        "weak_evidence": bool(metadata.get("weak_evidence")),
    }, topic, state["question"])


# 잡담 응답은 다양성이 아니라 "매번 일관되게 학사로 유도"가 목표라 8B에 맡기지 않고
# 규칙으로 인사/호응/그외를 분류해 고정(canned) 문구로 답한다.
# (8B가 few-shot 예시를 잘못 베껴 "ㄳ"에 인사로 답하던 문제 제거 + LLM 호출 절약)
# 이 핸들러는 이미 잡담으로 라우팅된 뒤라 학사 질문이 여기 올 일이 없어 start 매칭이 안전하다.
_GREETING_RE = re.compile(r'^\s*(안녕|반가|반갑|하이|방가|hi|hello|헬로)', re.IGNORECASE)
_ACK_RE = re.compile(
    r'^\s*(오+|와+|우와+|아+|어+|헐+)?\s*'   # 선택적 감탄사 prefix ("오 신기하다")
    r'(감사|고마|고맙|ㄳ|ㄱㅅ|땡큐|thank|넵|네|응|ㅇㅇ|ㅇㅋ|오케|오키|알겠|알았|굿|좋아|좋네|good|great|ok|'
    r'ㅋ|ㅎ|와|우와|대박|신기|헐|음|흠|짱|멋지|멋있|재밌|재미있|웃기|쩐|쩔|놀랍)',
    re.IGNORECASE,
)
_GREETING_REPLY = "안녕하세요! 저는 우송대학교 학사 질문을 도와드리는 코파일럿이에요. 궁금한 점 편하게 물어봐 주세요!"
_ACK_REPLY = "네! 다른 학사 관련 궁금한 점 있으면 편하게 물어봐 주세요."
_OFFTOPIC_REPLY = (
    "죄송하지만 그 질문에는 답해드리기 어려워요. 저는 우송대학교 학사 질문"
    "(수강신청·졸업·장학금 등)을 전문으로 돕는 코파일럿이에요. 학사 관련 궁금한 점을 편하게 물어봐 주세요!"
)
# '너 누구야'·'뭐 할 수 있어' 류 — 챗봇 자신에 대한 질문. 인사도 호응도 아니라 offtopic으로
# 떨어져 "답해드리기 어려워요"라고 거절했다(실측). 처음 쓰는 사용자가 가장 먼저 던지는 질문이라
# 첫 인상이 '못 하는 챗봇'이 된다. 날씨 같은 진짜 무관 질문과 달리 우리가 답할 수 있는 질문이다.
_SELFINTRO_RE = re.compile(
    # '챗봇'도 남겨 둔다 — 우리가 스스로를 코파일럿이라 불러도 학생은 여전히 '챗봇 누구야?'라고 묻는다.
    r'(너|넌|니|당신|챗봇|코파일럿|코파일럿아|봇|얘|쟤)\s*(는|은|가|이)?\s*(누구|뭐야|뭐니|뭔데|정체)|'
    r'이름\s*(이|은)?\s*(뭐|무엇)|'
    r'(뭘|뭐|무엇|어떤\s*걸?)\s*(할\s*수\s*있|도와|해\s*줄|알려\s*줄|가능)|'
    r'기능\s*(이|은)?\s*(뭐|무엇|어떻)|'
    r'자기\s*소개|소개\s*해|사용법|어떻게\s*쓰'
)
_SELFINTRO_REPLY = (
    "저는 우송대학교 학사 안내 코파일럿이에요. 수강신청·졸업요건·장학금·기숙사·학식·학사일정처럼 "
    "학교 생활에서 궁금한 걸 학교 공식 자료에서 찾아 답해드려요.\n"
    "예를 들어 '휴학 신청 방법', '오늘 학식 뭐야', '기숙사 비용 얼마야'처럼 물어봐 주세요!"
)


async def _handle_general(state: AgentState) -> dict:
    """잡담 응대 핸들러 — 인사/호응/그외를 규칙으로 분류해 고정(canned) 응답.

    잡담은 이미 게이트/라우팅에서 걸러져 여기로 온다. 응답은 8B에 맡기지 않고 고정 문구로
    내보내 일관성을 보장하고, few-shot 오복사("ㄳ"→인사) 문제를 제거한다.
    """
    await _log(state["db"], state["student_id"], "general")
    q = state["question"].strip()
    if _GREETING_RE.match(q):
        answer = _GREETING_REPLY
    # 자기소개는 호응(_ACK_RE)보다 먼저 본다 — '넌 뭐야?'처럼 호응 어휘와 겹칠 여지를 없애기 위함.
    # 여기만 search를 쓴다('그래서 너 누구야?'처럼 앞에 말이 붙어도 잡아야 해서).
    elif _SELFINTRO_RE.search(q):
        answer = _SELFINTRO_REPLY
    elif _ACK_RE.match(q):
        answer = _ACK_REPLY
    else:
        # 인사·호응도 아닌 '토픽 없는' 잉여 질문 → 큐레이션 FAQ에 있으면 검수 답변을 그대로.
        # (LLM 안 태움 = 환각 0. 임계값 미만이면 기존 offtopic 안내로 폴백)
        from app.services.faq_index import faq_lookup
        loop = asyncio.get_event_loop()
        hit = await loop.run_in_executor(None, faq_lookup, q)
        if hit:
            return {"answer": hit[0], "source": "faq", "source_file": None, "topic": "general"}
        answer = _OFFTOPIC_REPLY
    return {
        "answer": answer,
        "source": "chitchat",
        "source_file": None,
        "topic": "general",
    }


# ── 라우팅 함수들 ──────────────────────────────────────────────────

_HANDLER_MAP = {
    "done":        END,
    "classify":    "keyword_classify",
    "campus":      "handle_campus",
    "graduation":  "handle_graduation",
    "scholarship": "handle_scholarship",
    "schedule":    "handle_schedule",
    "department":  "handle_department",
    "dining":      "handle_dining",
    "weather":     "handle_weather",
    "my_grades":   "handle_my_grades",
    "rag":         "handle_rag_general",
    "general":     "handle_general",
}


def _route_pre_check(state: AgentState) -> str:
    if state.get("done"):
        return "done"
    if state.get("intent"):
        return state["intent"]
    return "classify"


def _route_keyword(state: AgentState) -> str:
    it = state.get("intent")
    if it == "campus":
        return "campus"
    if it == "schedule":
        return "schedule"
    if it == "my_grades":
        return "my_grades"
    if it == "no_data":
        return "no_data"
    return "embed"


def _route_chitchat_gate(state: AgentState) -> str:
    """잡담 게이트가 잡담으로 판정하면 잡담 핸들러 직행, 아니면 rewrite로 진행."""
    return "general" if state.get("intent") == "general" else "continue"


def _route_embedding(state: AgentState) -> str:
    score = state.get("confidence", 0.0)
    handler = state.get("intent")
    # general(잡담)이 1등이면 확신도와 무관하게 잡담 핸들러로 보낸다.
    # general은 검색할 문서가 없어 저신뢰 RAG 폴백으로 보내면 무조건 0건으로 실패한다
    # ("네" 같은 짧은 응답이 general 1등인데 확신도 0.58로 아래 게이트에 걸려 RAG로 빠지던 버그).
    if handler == "general":
        return "general"
    # 학과 안내(college_department)는 저신뢰여도 항상 DB 핸들러(handle_department)로 보낸다.
    # 이 토픽엔 옛 '단과대 소개' RAG 문서 몇 건이 남아 있어, '글로벌미디어AI영상학과 소개'처럼
    # 이름이 특이해 유사도가 낮은 학과 질문이 RAG로 새면 자유전공학부·솔브릿지 같은 엉뚱한
    # 대학 소개를 답한다(참고: services/school/department.py 도크스트링). 학과 핸들러는 DB로
    # 단과대·학부·학과를 모두 답하고, 못 찾으면 정직히 "못 찾았다"고 하므로 환각이 없다.
    if handler == "department":
        return "department"
    if score >= _HIGH_CONFIDENCE and handler:
        return handler
    # 저신뢰 폴백의 예외 — 분류된 topic에 Qdrant 문서가 0개인 경우(dining·campus·schedule처럼
    # 전용 핸들러가 DB·캐시로 답하는 토픽)엔 전용 핸들러로 보낸다. RAG로 보내 봐야 그 토픽의
    # 문서가 애초에 없어 검색이 헛돌고, 전용 핸들러가 갖고 있는 답이 영영 안 나온다.
    # 실측: '학식 뭐야' → '동캠은?'이 dining 0.568로 게이트에 걸려 RAG로 빠져 0건.
    # 핸들러가 답을 못 찾으면 각자의 0건 폴백(_handle_dining·_handle_schedule)이 RAG로 넘긴다.
    # handler == "rag"인 빈 topic은 해당 없음 — 그건 topic 필터만 풀고 전체 검색이 맞다.
    if state.get("topic_no_docs") and handler and handler != "rag":
        print(f"[Graph] 저신뢰({score:.3f})지만 '{handler}'는 문서 없이 답하는 핸들러 → RAG 폴백 대신 직행")
        return handler
    # 신뢰도 낮으면 LLM 분류 없이 topic 필터 없는 전체 RAG 검색
    return "rag"



# ── 그래프 빌드 ────────────────────────────────────────────────────

def _build_graph():
    g = StateGraph(AgentState)

    g.add_node("pre_check",         _pre_check)
    g.add_node("keyword_classify",  _keyword_classify)
    g.add_node("chitchat_gate",     _chitchat_gate)
    g.add_node("rewrite",           _rewrite)
    g.add_node("embedding_classify", _embedding_classify)
    g.add_node("handle_campus",     _handle_campus)
    g.add_node("handle_graduation", _handle_graduation)
    g.add_node("handle_schedule",   _handle_schedule)
    g.add_node("handle_scholarship",_handle_scholarship)
    g.add_node("handle_department", _handle_department)
    g.add_node("handle_dining",     _handle_dining)
    g.add_node("handle_weather",    _handle_weather)
    g.add_node("handle_my_grades",  _handle_my_grades)
    g.add_node("handle_rag_general",_handle_rag_general)
    g.add_node("handle_general",    _handle_general)
    g.add_node("handle_no_data",    _handle_no_data)

    g.set_entry_point("pre_check")

    g.add_conditional_edges("pre_check", _route_pre_check, _HANDLER_MAP)
    g.add_conditional_edges("keyword_classify", _route_keyword, {
        "campus":    "handle_campus",
        "schedule":  "handle_schedule",
        "my_grades": "handle_my_grades",
        "no_data":   "handle_no_data",
        "embed":     "chitchat_gate",
    })
    g.add_conditional_edges("chitchat_gate", _route_chitchat_gate, {
        "general":  "handle_general",
        "continue": "rewrite",
    })
    g.add_edge("rewrite", "embedding_classify")
    g.add_conditional_edges("embedding_classify", _route_embedding, {
        "campus":      "handle_campus",
        "graduation":  "handle_graduation",
        "scholarship": "handle_scholarship",
        "schedule":    "handle_schedule",
        "department":  "handle_department",
        "dining":      "handle_dining",
        "weather":     "handle_weather",
        "my_grades":   "handle_my_grades",
        "rag":         "handle_rag_general",
        "general":     "handle_general",
    })

    for handler in [
        "handle_campus", "handle_graduation", "handle_schedule", "handle_scholarship",
        "handle_department", "handle_dining", "handle_weather", "handle_my_grades", "handle_rag_general",
        "handle_general", "handle_no_data",
    ]:
        g.add_edge(handler, END)

    return g.compile()


# ── 공개 API ───────────────────────────────────────────────────────

@dataclass
class AgentResult:
    answer: str
    file_offer: dict | None = None
    file_download: dict | None = None
    map_card: dict | None = None
    schedule_card: dict | None = None
    dept_card: dict | None = None
    scholarship_card: dict | None = None
    weather_card: dict | None = None
    pending_context: dict | None = None
    intent: str | None = None
    topic: str | None = None
    source: str | None = None
    source_file: str | None = None
    rewritten_query: str | None = None
    login_required: bool = False   # 게스트가 개인 데이터 기능을 물었다 → 프론트가 로그인 버튼 표시


class AgentGraph:
    def __init__(self):
        self._graph = _build_graph()

    async def run(
        self,
        question: str,
        student_id: int | None,   # None = 게스트(비로그인)
        db: AsyncSession,
        pending_file: dict | None = None,
        pending_context: dict | None = None,
        prev_context: dict | None = None,
        file_confirm: bool | None = None,
    ) -> AgentResult:
        initial: AgentState = {
            "question": question,
            "student_id": student_id,
            "db": db,
            "pending_file": pending_file,
            "pending_context": pending_context,
            "prev_context": prev_context,
            "file_confirm": file_confirm,
            "intent": None,
            "confidence": 0.0,
            "search_query": None,
            "topic_no_docs": False,
            "answer": None,
            "file_offer": None,
            "file_download": None,
            "map_card": None,
            "schedule_card": None,
            "dept_card": None,
            "scholarship_card": None,
            "weather_card": None,
            "next_pending_context": None,
            "source": None,
            "source_file": None,
            "topic": None,
            "rewritten_query": None,
            "login_required": False,
            "done": False,
        }

        result = await self._graph.ainvoke(initial)

        return AgentResult(
            answer=result.get("answer") or "답변을 생성할 수 없습니다.",
            file_offer=result.get("file_offer"),
            file_download=result.get("file_download"),
            map_card=result.get("map_card"),
            schedule_card=result.get("schedule_card"),
            dept_card=result.get("dept_card"),
            scholarship_card=result.get("scholarship_card"),
            weather_card=result.get("weather_card"),
            pending_context=result.get("next_pending_context"),
            intent=result.get("intent"),
            topic=result.get("topic"),
            source=result.get("source"),
            source_file=result.get("source_file"),
            rewritten_query=result.get("rewritten_query"),
            login_required=bool(result.get("login_required")),
        )


agent_graph = AgentGraph()
