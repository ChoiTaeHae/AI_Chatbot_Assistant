"""
LangGraph 기반 학교 AI 에이전트

분류 흐름:
  pre_check → keyword_classify → embedding_classify → (신뢰도 낮으면) llm_classify
                                                      → 핸들러 노드 → END
"""
import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from langgraph.graph import StateGraph, END
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.agent_state import AgentState
from app.agents.intent import IntentType
from app.agents.topic_router import topic_router
from app.models.DB_Table import ChatLog
from app.services.llm_service import llm_service
from app.services.school.campus import CampusService
from app.services.school.graduation import graduation_service
from app.services.school.rag_general import answer_rag_general_question_with_metadata, _resolve_topic
from app.services.school.scholarship import answer_scholarship_question
from app.services.file_service import AVAILABLE_FILES

_campus_service = CampusService()

# 임베딩 유사도가 이 값 이상이면 LLM 분류 없이 임베딩 결과를 신뢰
_HIGH_CONFIDENCE = 0.60

# ── 캠퍼스 키워드 ─────────────────────────────────────────────────
_CAMPUS_KEYWORDS = [
    "건물", "위치", "캠퍼스", "강의실", "학과사무실", "도서관", "체육관", "식당", "호실", "층",
    "우송도서관", "산학협력관", "산학관", "학군단", "유학생기숙사", "기숙사",
    "철도물류관", "철도관", "보건의료과학관", "보건관", "교양교육관", "교양관",
    "우송관", "우송유치원", "유치원", "정례원", "사회복지융합관", "사복관",
    "서캠체육관", "SICA", "시카", "우송타워", "솔파인",
    "Culinary Center", "컬리너리", "식품건축관", "식품관", "건축관", "우송식품건축관",
    "학생회관", "미디어융합관", "미디어관", "우송예술회관", "예술회관",
    "Endicott Building", "엔디콧", "엔디컷",
    "테크노디자인센터", "테크노관", "국제경영센터", "국제관", "학술정보관",
    "대학본부", "자립관", "청솔관", "단정관", "독행관",
    "크로톤빌센터", "크로톤빌", "스터디홀",
    "어학센터", "어학원", "IT교육센터", "IT센터", "아이티센터",
    "뷰티센터", "뷰티관", "애견센터", "애견관",
    "오토센터", "자동차센터", "솔카오토테크", "우송솔카오토테크", "카오토테크",
    "스포츠센터", "우송스포츠센터", "유학생숙소",
    "보건의료관", "사회복지관", "국제경영관", "예술관",
]
_BUILDING_CODE_RE = re.compile(r'[WwEeSs]\d{1,2}')

POSITIVE_KEYWORDS = ["응", "네", "예", "ㅇㅇ", "보내줘", "보내", "좋아", "알겠어", "그래", "응응", "넹", "넵", "주세요"]
QUESTION_KEYWORDS = ["어떻게", "언제", "뭐야", "뭔데", "왜", "어디", "?", "？", "알려", "설명"]


def _is_campus_question(q: str) -> bool:
    return any(kw in q for kw in _CAMPUS_KEYWORDS) or bool(_BUILDING_CODE_RE.search(q))


def _is_confirmation(text: str) -> bool:
    if any(kw in text for kw in QUESTION_KEYWORDS):
        return False
    return any(kw in text for kw in POSITIVE_KEYWORDS)


def _with_file_offer(updates: dict, topic: str) -> dict:
    files = AVAILABLE_FILES.get(topic, [])
    if not files:
        return updates
    filename = files[0]
    stem = Path(filename).stem
    return {
        **updates,
        "answer": updates["answer"] + f"\n\n혹시 **{stem}** 파일이 필요하시면 보내드릴까요?",
        "file_offer": {"topic": topic, "filename": filename},
    }


async def _log(db: AsyncSession, student_id: int | None, intent: str) -> None:
    try:
        db.add(ChatLog(student_id=student_id, intent=intent))
        await db.commit()
    except Exception as e:
        print(f"[Graph] 채팅 로그 저장 실패 (무시): {e}")


# ── 노드 함수들 ────────────────────────────────────────────────────

async def _pre_check(state: AgentState) -> dict:
    """파일 확인 응답 및 멀티턴 컨텍스트 처리"""
    if state.get("pending_file") and _is_confirmation(state["question"]):
        pf = state["pending_file"]
        stem = Path(pf["filename"]).stem
        return {
            "answer": f"네, {stem}을 보내드릴게요!",
            "file_download": {
                "topic": pf["topic"],
                "filename": pf["filename"],
                "url": f"/api/files/{pf['topic']}/{pf['filename']}",
            },
            "source": "file_download",
            "source_file": pf["filename"],
            "topic": pf["topic"],
            "done": True,
        }

    # 진행 중인 멀티턴 → context type을 intent로 세팅해서 해당 핸들러로 직행
    if state.get("pending_context"):
        ctx_type = state["pending_context"].get("type", "general")
        return {"intent": ctx_type, "done": False}

    return {"done": False}


async def _keyword_classify(state: AgentState) -> dict:
    """키워드 기반 캠퍼스 분류 (0ms)"""
    if _is_campus_question(state["question"]):
        print("[Graph] 키워드 분류 → campus")
        return {"intent": "campus"}
    return {"intent": None}


async def _embedding_classify(state: AgentState) -> dict:
    """임베딩 유사도 기반 분류"""
    loop = asyncio.get_event_loop()
    try:
        intent, score = await loop.run_in_executor(
            None, topic_router.route_with_score, state["question"]
        )
        intent_val = intent.value if intent else None
        print(f"[Graph] 임베딩 분류 → {intent_val} ({score:.3f})")
        return {"intent": intent_val, "confidence": score}
    except Exception as e:
        print(f"[Graph] 임베딩 분류 실패: {e}")
        return {"intent": None, "confidence": 0.0}


async def _llm_classify(state: AgentState) -> dict:
    """LLM 기반 분류 (임베딩 신뢰도 낮을 때 fallback)"""
    intent = await llm_service.classify_intent(state["question"])
    print(f"[Graph] LLM 분류 → {intent}")
    return {"intent": intent}


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
    answer, metadata = await graduation_service.answer_graduation_with_metadata(
        question=state["question"], student_id=state["student_id"], db=state["db"]
    )
    return _with_file_offer({
        "answer": answer,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": metadata.get("topic") or "graduation",
    }, "graduation")


async def _handle_scholarship(state: AgentState) -> dict:
    await _log(state["db"], state["student_id"], "scholarship")
    answer, next_ctx, metadata = await answer_scholarship_question(
        state["question"],
        student_id=state["student_id"],
        db=state["db"],
        pending_context=state.get("pending_context"),  # 멀티턴 컨텍스트 전달
    )
    return {
        "answer": answer,
        "next_pending_context": next_ctx,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": metadata.get("topic") or "scholarship",
    }


async def _handle_student_support(state: AgentState) -> dict:
    await _log(state["db"], state["student_id"], "student_support")
    answer, metadata = await answer_rag_general_question_with_metadata(state["question"])
    return {
        "answer": answer,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": "student_support",
    }


async def _handle_rotc(state: AgentState) -> dict:
    await _log(state["db"], state["student_id"], "rotc")
    answer, metadata = await answer_rag_general_question_with_metadata(state["question"])
    return {
        "answer": answer,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": "rotc",
    }


async def _handle_rag_general(state: AgentState) -> dict:
    topic = _resolve_topic(state["question"])
    await _log(state["db"], state["student_id"], topic)
    answer, metadata = await answer_rag_general_question_with_metadata(state["question"])
    return _with_file_offer({
        "answer": answer,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": metadata.get("topic") or topic,
    }, topic)


async def _handle_general(state: AgentState) -> dict:
    await _log(state["db"], state["student_id"], "general")
    answer = await llm_service.answer(state["question"])
    return {
        "answer": answer,
        "source": "llm",
        "source_file": None,
        "topic": "general",
    }


# ── 라우팅 함수들 ──────────────────────────────────────────────────

def _route_pre_check(state: AgentState) -> str:
    if state.get("done"):
        return "done"
    if state.get("intent"):  # pending_context에서 intent가 세팅된 경우 분류 생략
        return state["intent"]
    return "classify"


def _route_keyword(state: AgentState) -> str:
    return "campus" if state.get("intent") == "campus" else "embed"


def _route_embedding(state: AgentState) -> str:
    score = state.get("confidence", 0.0)
    intent = state.get("intent")

    if score >= _HIGH_CONFIDENCE and intent:
        return _resolve_rag_subtype(intent, state["question"])
    return "llm"


def _route_llm(state: AgentState) -> str:
    intent = state.get("intent") or "general"
    return _resolve_rag_subtype(intent, state["question"])


def _resolve_rag_subtype(intent: str, question: str) -> str:
    """rag_general이면 장학금/학생지원/ROTC 여부를 추가로 확인"""
    if intent == "rag_general":
        topic = _resolve_topic(question)
        if topic == "scholarship":
            return "scholarship"
        if topic == "student_support":
            return "student_support"
        if topic == "rotc":
            return "rotc"
        return "rag_general"
    return intent


# ── 그래프 빌드 ────────────────────────────────────────────────────

def _build_graph():
    g = StateGraph(AgentState)

    g.add_node("pre_check", _pre_check)
    g.add_node("keyword_classify", _keyword_classify)
    g.add_node("embedding_classify", _embedding_classify)
    g.add_node("llm_classify", _llm_classify)
    g.add_node("handle_campus", _handle_campus)
    g.add_node("handle_graduation", _handle_graduation)
    g.add_node("handle_scholarship", _handle_scholarship)
    g.add_node("handle_student_support", _handle_student_support)
    g.add_node("handle_rotc", _handle_rotc)
    g.add_node("handle_rag_general", _handle_rag_general)
    g.add_node("handle_general", _handle_general)

    g.set_entry_point("pre_check")

    _HANDLER_MAP = {
        "done": END,
        "classify": "keyword_classify",
        "campus": "handle_campus",
        "graduation": "handle_graduation",
        "scholarship": "handle_scholarship",
        "student_support": "handle_student_support",
        "rotc": "handle_rotc",
        "rag_general": "handle_rag_general",
        "general": "handle_general",
    }

    g.add_conditional_edges("pre_check", _route_pre_check, _HANDLER_MAP)
    g.add_conditional_edges("keyword_classify", _route_keyword, {
        "campus": "handle_campus",
        "embed": "embedding_classify",
    })
    g.add_conditional_edges("embedding_classify", _route_embedding, {
        "campus": "handle_campus",
        "graduation": "handle_graduation",
        "scholarship": "handle_scholarship",
        "student_support": "handle_student_support",
        "rotc": "handle_rotc",
        "rag_general": "handle_rag_general",
        "general": "handle_general",
        "llm": "llm_classify",
    })
    g.add_conditional_edges("llm_classify", _route_llm, {
        "campus": "handle_campus",
        "graduation": "handle_graduation",
        "scholarship": "handle_scholarship",
        "student_support": "handle_student_support",
        "rotc": "handle_rotc",
        "rag_general": "handle_rag_general",
        "general": "handle_general",
    })

    for handler in [
        "handle_campus", "handle_graduation", "handle_scholarship",
        "handle_student_support", "handle_rotc", "handle_rag_general", "handle_general",
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
    ) -> AgentResult:
        initial: AgentState = {
            "question": question,
            "student_id": student_id,
            "db": db,
            "pending_file": pending_file,
            "pending_context": pending_context,
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
