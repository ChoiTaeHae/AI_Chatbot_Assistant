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
from app.services.school.campus import CampusService
from app.services.school.graduation import graduation_service
from app.services.school.rag_general import answer_rag_general_question_with_metadata
from app.services.school.scholarship import answer_scholarship_question
from app.services.file_service import AVAILABLE_FILES

_campus_service = CampusService()

_HIGH_CONFIDENCE = 0.60
_TOPIC_SWITCH_CONFIDENCE = 0.75

_BUILDING_CODE_RE = re.compile(r'^[WwEeSs]\d{1,2}$')

POSITIVE_KEYWORDS = [
    # 기본 긍정 (단답/구어체 포함)
    "응", "네", "예", "응응", "네네", "ㅇㅇ", "웅", "웅웅", "어", "어어",
    "넵", "넹", "옙", "얍",
    
    # 파일 요청 및 행동 유도
    "주세요", "줘", "줘요", "줘봐", "내놔", "보내줘", "보내줘요", "보내주세요",
    "보내봐", "보내봐봐", "부탁해", "부탁해요", "부탁드립니다", "주라", "줘라", "줘봐라"
    
    # 긍정 동의 및 호응
    "좋아", "좋아요", "알겠어", "알겠습니다", "그래", "그래요", "그럼", "그럼요",
    "당연", "물론", "당근", "당빠", "맞아", "맞아요", "그치", "그렇지", "좋지",
    
    # 영어 및 인터넷 용어/초성
    "오케", "오케이", "ok", "OK", "Ok", "ㅇㅋ", "ㅇㅋㅇㅋ", "오키", 
    "콜", "고고", "ㄱㄱ", "고", "조아", "쪼아",
    
    # 필요 표현
    "주셔", "주셔도", "바라요", "원해요", "필요해요", "필요합니다", "필요해",
    "요청합니다", "요청해", "원해",
    
    # 음슴체
    "좋음", "필요함", "주셈", "보내주셈", "주삼", "콜임", "원함", "동의함"
]

NEGATIVE_KEYWORDS = [
    # 명확한 부정
    "아니요", "아니", "아니다", "아니에요", "아닙니다",
    
    # 영어 및 인터넷 용어/초성
    "no", "No", "NO", "놉", "노노", "ㄴㄴ", "ㄴ", "패스", "엑스", "에바",
    
    # 구어체 / 거절 / 만류
    "됐어", "됐습니다", "안해도돼", "안해도", "안해", "안할래",
    "싫어", "싫어요", "싫습니다", "별로", "별로야", "사양할게", "사양할게요",
    "괜찮아", "괜찮아요", "괜찮습니다", "괜찮", 
    "필요없어", "필요없어요", "필요없습니다",
    "안받을게", "안받아도돼", "안받아", "안주셔도", "안주셔도됩니다",
    "그만", "그만해요", "치워",
    
    # 음슴체
    "아님", "됐음", "싫음", "괜찮음", "필요없음", "안받음", "사양함", "안함", "별로임", "패스함"
]


QUESTION_KEYWORDS = ["어떻게", "언제", "뭐야", "뭔데", "왜", "어디", "?", "？", "알려", "설명"]


def _is_campus_question(q: str) -> bool:
    return bool(_BUILDING_CODE_RE.search(q))


def _is_confirmation(text: str) -> bool:
    if any(kw in text for kw in QUESTION_KEYWORDS):
        return False
    return any(kw in text for kw in POSITIVE_KEYWORDS)


def _is_rejection(text: str) -> bool:
    """명확한 거절/부정 표현인지 확인"""
    return any(kw in text for kw in NEGATIVE_KEYWORDS)


def _with_file_offer(updates: dict, topic: str) -> dict:
    files = AVAILABLE_FILES.get(topic, [])
    if not files:
        return updates

    if len(files) == 1:
        stem = Path(files[0]).stem
        offer_text = f"\n\n혹시 **{stem}** 파일이 필요하시면 보내드릴까요?"
    else:
        offer_text = f"\n\n관련 파일이 {len(files)}개 있어요. 드릴까요?"

    return {
        **updates,
        "answer": updates["answer"] + offer_text,
        # show_buttons=False: 첫 응답에는 버튼 숨김, '응' 입력 후에 True로 전환
        "file_offer": {"topic": topic, "files": files, "show_buttons": False},
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

    pending_file 구조:
      단일 파일 (구버전 호환): { topic, filename }
      다중 파일 (신버전):     { topic, files: [str, ...] }

    다중 파일은 프론트 버튼으로 직접 다운로드하므로
    텍스트 '응' 응답은 파일이 정확히 1개일 때만 처리한다.
    """
    pf = state.get("pending_file")
    if pf:
        q = state["question"]

        # 1순위: 거절 표현 체크 → 바로 종료
        if _is_rejection(q):
            return {
                "answer": "알겠습니다! 다른 궁금하신 점이 있으시면 언제든지 질문해 주세요. 😊",
                "done": True,
            }

        # 2순위: 긍정 표현 체크
        if _is_confirmation(q):
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
            # 파일이 2개 이상 → 버튼 선택 화면으로 전환
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


async def _embedding_classify(state: AgentState) -> dict:
    """임베딩 유사도 기반 분류 — (topic_name, handler_type, score) 반환"""
    loop = asyncio.get_event_loop()
    try:
        topic_name, handler_type, score = await loop.run_in_executor(
            None, topic_router.route_with_score, state["question"]
        )
        print(f"[Graph] 임베딩 분류 → topic={topic_name} handler={handler_type} ({score:.3f})")

        prev = state.get("prev_context")
        prev_topic = prev.get("prev_topic") if prev else None

        # 신뢰도 낮으면 이전 topic으로 fallback
        if score < _HIGH_CONFIDENCE and prev_topic:
            prev_info = topic_router._proto_vecs.get(prev_topic, {})
            prev_handler = prev_info.get("handler_type", "rag")
            print(f"[Graph] 임베딩 신뢰도 낮음 → 이전 topic '{prev_topic}' 사용")
            return {"intent": prev_handler, "topic": prev_topic, "confidence": score}

        # topic이 바뀌었지만 전환 신뢰도 미달 → 이전 topic 유지
        if prev_topic and topic_name != prev_topic and score < _TOPIC_SWITCH_CONFIDENCE:
            prev_info = topic_router._proto_vecs.get(prev_topic, {})
            prev_handler = prev_info.get("handler_type", "rag")
            print(f"[Graph] topic 전환 신뢰도 미달 ({score:.3f} < {_TOPIC_SWITCH_CONFIDENCE}) → 이전 topic '{prev_topic}' 유지")
            return {"intent": prev_handler, "topic": prev_topic, "confidence": score}

        return {"intent": handler_type, "topic": topic_name, "confidence": score}
    except Exception as e:
        print(f"[Graph] 임베딩 분류 실패: {e}")
        return {"intent": None, "topic": None, "confidence": 0.0}



_KEYWORD_TOPIC_MAP: list[tuple[list[str], str]] = [
    (["공결", "출석인정", "출석 인정"], "absence"),
]


async def _keyword_classify(state: AgentState) -> dict:
    """건물 코드 정규식 기반 campus 분류, 명확한 키워드 → topic 직행 (0ms)"""
    q = state["question"]
    if _is_campus_question(q):
        print("[Graph] 키워드 분류 → campus")
        return {"intent": "campus"}
    for keywords, topic in _KEYWORD_TOPIC_MAP:
        if any(kw in q for kw in keywords):
            print(f"[Graph] 키워드 분류 → {topic} ({[kw for kw in keywords if kw in q]})")
            return {"intent": "rag", "topic": topic}
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


async def _handle_graduation(state: AgentState) -> dict:
    await _log(state["db"], state["student_id"], "graduation")
    prev_prefix = _build_prev_prefix(state)
    enriched_question = prev_prefix + state["question"] if prev_prefix else state["question"]
    answer, metadata = await graduation_service.answer_graduation_with_metadata(
        question=enriched_question, student_id=state["student_id"], db=state["db"]
    )
    answer = _append_contact_info(answer, metadata)
    return _with_file_offer({
        "answer": answer,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": metadata.get("topic") or "graduation",
    }, "graduation")


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
    return {
        "answer": answer,
        "next_pending_context": next_ctx,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": metadata.get("topic") or "scholarship",
    }


async def _handle_rag_general(state: AgentState) -> dict:
    """RAG 검색 핸들러 — state["topic"]을 Qdrant 필터로 사용"""
    topic = state.get("topic") or "rag_general"
    await _log(state["db"], state["student_id"], topic)

    prev_prefix = _build_prev_prefix(state)
    enriched_question = prev_prefix + state["question"] if prev_prefix else None

    answer, metadata = await answer_rag_general_question_with_metadata(
        state["question"],          # 검색/rewrite용 원본 질문
        topic=topic,
        context_question=enriched_question,  # LLM 맥락용 (이전 주제 힌트 포함)
    )
    answer = _append_contact_info(answer, metadata)
    return _with_file_offer({
        "answer": answer,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": metadata.get("topic") or topic,
    }, topic)


async def _handle_general(state: AgentState) -> dict:
    await _log(state["db"], state["student_id"], "general")
    prev_prefix = _build_prev_prefix(state)
    enriched_question = prev_prefix + state["question"] if prev_prefix else state["question"]
    prompt = GENERAL_HANDLER_PROMPT.format(question=enriched_question)
    answer = await llm_service.answer(prompt)
    return {
        "answer": answer,
        "source": "llm",
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
    intent = state.get("intent")
    if intent == "campus":
        return "campus"
    if intent == "rag":
        return "rag"
    return "embed"


def _route_embedding(state: AgentState) -> str:
    score = state.get("confidence", 0.0)
    handler = state.get("intent")
    if score >= _HIGH_CONFIDENCE and handler:
        return handler
    # 신뢰도 낮으면 LLM 분류 없이 topic 필터 없는 전체 RAG 검색
    return "rag"



# ── 그래프 빌드 ────────────────────────────────────────────────────

def _build_graph():
    g = StateGraph(AgentState)

    g.add_node("pre_check",         _pre_check)
    g.add_node("keyword_classify",  _keyword_classify)
    g.add_node("embedding_classify", _embedding_classify)
    g.add_node("handle_campus",     _handle_campus)
    g.add_node("handle_graduation", _handle_graduation)
    g.add_node("handle_scholarship",_handle_scholarship)
    g.add_node("handle_rag_general",_handle_rag_general)
    g.add_node("handle_general",    _handle_general)

    g.set_entry_point("pre_check")

    g.add_conditional_edges("pre_check", _route_pre_check, _HANDLER_MAP)
    g.add_conditional_edges("keyword_classify", _route_keyword, {
        "campus": "handle_campus",
        "rag":    "handle_rag_general",
        "embed":  "embedding_classify",
    })
    g.add_conditional_edges("embedding_classify", _route_embedding, {
        "campus":      "handle_campus",
        "graduation":  "handle_graduation",
        "scholarship": "handle_scholarship",
        "rag":         "handle_rag_general",
        "general":     "handle_general",
    })

    for handler in [
        "handle_campus", "handle_graduation", "handle_scholarship",
        "handle_rag_general", "handle_general",
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
    pending_context: dict | None = None
    intent: str | None = None
    topic: str | None = None
    source: str | None = None
    source_file: str | None = None


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
    ) -> AgentResult:
        initial: AgentState = {
            "question": question,
            "student_id": student_id,
            "db": db,
            "pending_file": pending_file,
            "pending_context": pending_context,
            "prev_context": prev_context,
            "intent": None,
            "confidence": 0.0,
            "answer": None,
            "file_offer": None,
            "file_download": None,
            "map_card": None,
            "next_pending_context": None,
            "source": None,
            "source_file": None,
            "topic": None,
            "done": False,
        }

        result = await self._graph.ainvoke(initial)

        return AgentResult(
            answer=result.get("answer") or "답변을 생성할 수 없습니다.",
            file_offer=result.get("file_offer"),
            file_download=result.get("file_download"),
            map_card=result.get("map_card"),
            pending_context=result.get("next_pending_context"),
            intent=result.get("intent"),
            topic=result.get("topic"),
            source=result.get("source"),
            source_file=result.get("source_file"),
        )


agent_graph = AgentGraph()
