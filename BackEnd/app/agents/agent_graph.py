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
from app.services.school.campus import CampusService, has_building_hit
from app.services.school.department import answer_department_question
from app.services.school.graduation import graduation_service
from app.services.school.schedule import schedule_service
from app.services.school.rag_general import answer_rag_general_question_with_metadata, _rewrite_query, _distinctive_terms
from app.services.school.scholarship import answer_scholarship_question
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
_NON_RAG_HANDLERS = {"campus", "graduation", "scholarship", "schedule", "general"}

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
    r'지원|모집|혜택|자격|조건|정보|대해|되나|하나요|인가요|추천|목록|'
    # 시설 이용·대여·예약 등 '서비스/절차' 질문 — 위치가 아니라 그 정보(RAG)를 원하는 것
    r'대여|대관|예약|이용|사용|빌리|운영|시간|요금|가격|비용'
)
# 행위(획득·발급·신청·대여·예약 등) 동사 — 위치 의도('어디')가 있어도 이게 있으면 campus 억제.
# '어디서 받아요'는 '동아리방이 어디냐'가 아니라 '열쇠를 어디서 받냐'는 절차 질문이라, 건물 별칭이
# 우연히 잡혀도(예: '동아리방 열쇠 어디서 받아요' → 학생회관 별칭 '동아리방') 지도 대신 RAG/FAQ로.
# ('동아리방 어디야?' 같은 순수 위치질문은 행위어가 없어 그대로 campus로 간다)
_PROCEDURE_RE = re.compile(r'열쇠|받아|받을|받나|받으러|받는|받고|받습|발급|신청|빌리|빌려|대여|반납|예약|대출')


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
    r"(규칙|제한|필터|검열|제약)\s*[이가]?\s*없는\s*(AI|인공지능|챗봇|모델|assistant|어시스턴트)",
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
    "질문을 도와드리는 챗봇이에요. 학사 관련해서 궁금한 점을 편하게 물어봐 주세요! 😊"
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

        # 새 topic에 문서가 하나도 없으면 전환 취소 → 이전 topic 유지
        # (빈 topic 전환 → 검색 0건 → 환각 답변으로 이어지는 함정 방지)
        # RAG 핸들러로의 전환만 검사 — graduation/campus/scholarship/general(chitchat 포함)은
        # Qdrant 문서가 아닌 DB 조회/코드 파싱/전용 로직으로 답하므로 문서 개수가 무의미함
        # 단, 새 분류가 확신(score >= _HIGH_CONFIDENCE)이면 전환한다 — 사용자가 명확히 새
        # topic을 물었으면, 빈 topic이어도 RAG가 "자료 없음"을 정직히 답하는 게(0건 fallback)
        # 엉뚱한 이전 topic 답변보다 낫다. 이전 topic도 비어있을 때 계속 갇히는 버그 방지.
        if (prev_topic and topic_name != prev_topic and handler_type == "rag"
                and score < _HIGH_CONFIDENCE):
            try:
                doc_count = await loop.run_in_executor(
                    None, rag_service.vector_store.count_by_topic, topic_name
                )
                if doc_count == 0:
                    prev_handler, prev_route_topic = _resolve_prev_route(prev_topic)
                    if prev_handler:
                        print(f"[Graph] '{topic_name}' 문서 0개 → 전환 취소, 이전 topic '{prev_topic}' 유지 (handler={prev_handler})")
                        return {"intent": prev_handler, "topic": prev_route_topic, "confidence": score}
            except Exception as e:
                print(f"[Graph] topic 문서 수 확인 실패 (전환 진행): {e}")

        return {"intent": handler_type, "topic": topic_name, "confidence": score}
    except Exception as e:
        print(f"[Graph] 임베딩 분류 실패: {e}")
        return {"intent": None, "topic": None, "confidence": 0.0}



async def _keyword_classify(state: AgentState) -> dict:
    """규칙 기반 fast-path 분류 (0ms) — campus 건물코드 / 학사일정 날짜질문"""
    if _is_campus_question(state["question"]):
        print("[Graph] 키워드 분류 → campus")
        return {"intent": "campus"}
    # 건물명이 DB에 매칭되고, 위치 의도가 있거나(→위치) '정보·절차 의도가 없으면'(건물명만 침) campus.
    #   '동캠학생회관'·'학군단 어디' → campus / '학군단 뭐야'·'학군단 모집 언제' → RAG로 넘김.
    # (regex 먼저 걸러 대부분의 질문은 DB 조회 없이 통과 — 정보의도어가 있으면 즉시 skip)
    q = state["question"]
    if not _PROCEDURE_RE.search(q) and (_LOCATION_INTENT_RE.search(q) or not _INFO_INTENT_RE.search(q)) and await has_building_hit(q):
        print("[Graph] 키워드 분류 → campus (건물명 매칭)")
        return {"intent": "campus"}
    if _is_schedule_date_question(state["question"]):
        print("[Graph] 키워드 분류 → schedule (날짜 질문 fast-path)")
        return {"intent": "schedule", "topic": "schedule"}
    return {"intent": None}


async def _handle_campus(state: AgentState) -> dict:
    await _log(state["db"], state["student_id"], "campus")
    result = await _campus_service.search_location(state["question"])
    return {
        "answer": result.get("answer", "위치 정보를 찾을 수 없습니다."),
        "map_card": result.get("map_card") if result.get("found") else None,
        "source": result.get("source") or (result.get("map_card") or {}).get("source"),
        "source_file": None,
        "topic": "campus",
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


async def _handle_graduation(state: AgentState) -> dict:
    await _log(state["db"], state["student_id"], "graduation")
    # 졸업 분기(학과 감지·유형 분류)는 반드시 '현재 질문' 기준이어야 한다.
    # enriched(이전 주제 프리픽스)를 넘기면 "간호학과 졸업요건" 뒤 "내 학과 졸업요건"이
    # 프리픽스의 '간호학과'를 학과로 오인 → 다른 학과 요건이 나오는 치명적 버그.
    answer, metadata = await graduation_service.answer_graduation_with_metadata(
        question=state["question"], student_id=state["student_id"], db=state["db"]
    )
    answer = _append_contact_info(answer, metadata)
    return _with_file_offer({
        "answer": answer,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": metadata.get("topic") or "graduation",
    }, "graduation", state["question"])


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
        print("[Graph] 학사일정 매칭 0건 → RAG 폴백")
        return await _handle_rag_general({**state, "topic": None})

    answer = _append_contact_info(answer, metadata)
    return {
        "answer": answer,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": metadata.get("topic") or "schedule",
        "schedule_card": metadata.get("schedule_card"),
    }


async def _handle_scholarship(state: AgentState) -> dict:
    await _log(state["db"], state["student_id"], "scholarship")
    prev_prefix = _build_prev_prefix(state)
    enriched_question = prev_prefix + state["question"] if prev_prefix else state["question"]
    answer, next_ctx, metadata = await answer_scholarship_question(
        enriched_question,
        student_id=state["student_id"],
        db=state["db"],
        pending_context=state.get("pending_context"),
    )
    answer = _append_contact_info(answer, metadata)
    return _with_file_offer({
        "answer": answer,
        "next_pending_context": next_ctx,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": metadata.get("topic") or "scholarship",
        "files_to_offer": metadata.get("files_to_offer", []),
    }, metadata.get("topic") or "scholarship", state["question"])


async def _handle_rag_general(state: AgentState) -> dict:
    """RAG 검색 핸들러 — state["topic"]을 Qdrant 필터로 사용"""
    topic = state.get("topic") or "rag_general"
    await _log(state["db"], state["student_id"], topic)

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
_GREETING_REPLY = "안녕하세요! 저는 우송대학교 학사 질문을 도와드리는 챗봇이에요. 궁금한 점 편하게 물어봐 주세요!"
_ACK_REPLY = "네! 다른 학사 관련 궁금한 점 있으면 편하게 물어봐 주세요."
_OFFTOPIC_REPLY = (
    "죄송하지만 그 질문에는 답해드리기 어려워요. 저는 우송대학교 학사 질문"
    "(수강신청·졸업·장학금 등)을 전문으로 돕는 챗봇이에요. 학사 관련 궁금한 점을 편하게 물어봐 주세요!"
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
    if score >= _HIGH_CONFIDENCE and handler:
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
    g.add_node("handle_rag_general",_handle_rag_general)
    g.add_node("handle_general",    _handle_general)

    g.set_entry_point("pre_check")

    g.add_conditional_edges("pre_check", _route_pre_check, _HANDLER_MAP)
    g.add_conditional_edges("keyword_classify", _route_keyword, {
        "campus":   "handle_campus",
        "schedule": "handle_schedule",
        "embed":    "chitchat_gate",
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
        "rag":         "handle_rag_general",
        "general":     "handle_general",
    })

    for handler in [
        "handle_campus", "handle_graduation", "handle_schedule", "handle_scholarship",
        "handle_department", "handle_rag_general", "handle_general",
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
    pending_context: dict | None = None
    intent: str | None = None
    topic: str | None = None
    source: str | None = None
    source_file: str | None = None
    rewritten_query: str | None = None


class AgentGraph:
    def __init__(self):
        self._graph = _build_graph()

    async def run(
        self,
        question: str,
        student_id: int,
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
            "answer": None,
            "file_offer": None,
            "file_download": None,
            "map_card": None,
            "schedule_card": None,
            "dept_card": None,
            "next_pending_context": None,
            "source": None,
            "source_file": None,
            "topic": None,
            "rewritten_query": None,
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
            pending_context=result.get("next_pending_context"),
            intent=result.get("intent"),
            topic=result.get("topic"),
            source=result.get("source"),
            source_file=result.get("source_file"),
            rewritten_query=result.get("rewritten_query"),
        )


agent_graph = AgentGraph()
