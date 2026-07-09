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
_NON_RAG_HANDLERS = {"campus", "graduation", "scholarship", "general"}

_BUILDING_CODE_RE = re.compile(r'^[WwEeSs]\d{1,2}$')

def _is_campus_question(q: str) -> bool:
    return bool(_BUILDING_CODE_RE.search(q))


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


async def _embedding_classify(state: AgentState) -> dict:
    """임베딩 유사도 기반 분류 — (topic_name, handler_type, score, all_scores) 사용"""
    loop = asyncio.get_event_loop()
    try:
        topic_name, handler_type, score, all_scores = await loop.run_in_executor(
            None, topic_router.route_with_score, state["question"]
        )
        print(f"[Graph] 임베딩 분류 → topic={topic_name} handler={handler_type} ({score:.3f})")

        prev = state.get("prev_context")
        prev_topic = prev.get("prev_topic") if prev else None
        # 잡담(general)은 stickiness 앵커가 되지 않음 — 잡담 한마디로 진행 중이던
        # RAG 맥락이 끊기고 근거 없는 general 답변에 갇히는 것을 방지 (2차 방어선,
        # 1차는 chat_service의 prev_context 구성 단계에서 잡담을 건너뛰는 것)
        if prev_topic == "general":
            prev_topic = None

        # 신뢰도 낮으면 이전 topic으로 fallback.
        # 단, 새 topic이 이전 topic보다 _SWITCH_MARGIN 이상 우세하면(명확한 새 질문)
        # 저신뢰여도 전환한다 — "공결신청하고싶어"가 이전 graduation에 갇히는 것을 방지.
        if score < _HIGH_CONFIDENCE and prev_topic:
            prev_cmp_score = all_scores.get(prev_topic) or 0.0
            if score - prev_cmp_score < _SWITCH_MARGIN:
                prev_handler, prev_route_topic = _resolve_prev_route(prev_topic)
                if prev_handler:
                    print(
                        f"[Graph] 임베딩 신뢰도 낮음 & 이전 대비 우세 미달 "
                        f"(새 {topic_name}={score:.3f} vs 이전 {prev_topic}={prev_cmp_score:.3f}) "
                        f"→ 이전 topic 사용 (handler={prev_handler})"
                    )
                    return {"intent": prev_handler, "topic": prev_route_topic, "confidence": score}
            # 새 topic이 이전보다 확실히 우세하거나 prev_topic 해석 불가 → 현재 분류로 진행

        # topic이 바뀌는 경우: 새 topic이 이전 topic보다 확실히 우세할 때만 전환.
        # 단, 새 분류가 확신(>= _HIGH_CONFIDENCE)이면 스티키니스를 적용하지 않고 전환한다
        # ("공결신청하고싶어"가 absence=0.728로 확실한데 graduation에 갇히는 것을 방지).
        prev_score = all_scores.get(prev_topic) if prev_topic else None
        if score < _HIGH_CONFIDENCE and prev_topic and topic_name != prev_topic and prev_score is not None:
            if score - prev_score < _SWITCH_MARGIN:
                prev_handler, prev_route_topic = _resolve_prev_route(prev_topic)
                print(
                    f"[Graph] topic 전환 우세 미달 (새 {topic_name}={score:.3f} vs "
                    f"이전 {prev_topic}={prev_score:.3f}, 차이 {score - prev_score:.3f} < {_SWITCH_MARGIN})"
                    f" → 이전 topic 유지"
                )
                return {
                    "intent": prev_handler or handler_type,
                    "topic": prev_route_topic or topic_name,
                    "confidence": score,
                }
            print(
                f"[Graph] topic 전환 승인 (새 {topic_name}={score:.3f} vs "
                f"이전 {prev_topic}={prev_score:.3f}, 차이 {score - prev_score:.3f} ≥ {_SWITCH_MARGIN})"
            )

        # 새 topic에 문서가 하나도 없으면 전환 취소 → 이전 topic 유지
        # (빈 topic 전환 → 검색 0건 → 환각 답변으로 이어지는 함정 방지)
        # RAG 핸들러로의 전환만 검사 — graduation/campus/scholarship/general(chitchat 포함)은
        # Qdrant 문서가 아닌 DB 조회/코드 파싱/전용 로직으로 답하므로 문서 개수가 무의미함
        if prev_topic and topic_name != prev_topic and handler_type == "rag":
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
    """건물 코드 정규식 기반 campus 분류 (0ms)"""
    if _is_campus_question(state["question"]):
        print("[Graph] 키워드 분류 → campus")
        return {"intent": "campus"}
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
    }, "graduation", state["question"])


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
    )
    answer = _append_contact_info(answer, metadata)
    return _with_file_offer({
        "answer": answer,
        "source": metadata.get("source"),
        "source_file": metadata.get("source_file"),
        "topic": metadata.get("topic") or topic,
        "rewritten_query": metadata.get("rewritten_query"),
        "files_to_offer": metadata.get("files_to_offer", []),
    }, topic, state["question"])


async def _handle_general(state: AgentState) -> dict:
    """잡담 응대 핸들러. 현재 topic이 항상 "general"이고 chat_service가 이전 대화에서
    general 턴은 건너뛰므로 prev_topic이 "general"과 같아질 일이 없다 —
    즉 _build_prev_prefix는 이 핸들러에서 항상 빈 문자열을 반환해 사용하지 않는다."""
    await _log(state["db"], state["student_id"], "general")
    prompt = GENERAL_HANDLER_PROMPT.format(question=state["question"])
    # 잡담은 다양성보다 "매번 일관되게 유도"가 목표이므로 기본값(0.3) 사용
    answer = await llm_service.answer(prompt)
    # few-shot 형식("질문:.../답:...")을 모델이 그대로 따라 출력하는 경우 방지
    if "답:" in answer:
        answer = answer.split("답:")[-1].strip()
    if answer.startswith("질문:"):
        answer = answer.split("\n", 1)[-1].strip()
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
    return "campus" if state.get("intent") == "campus" else "embed"


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
            "answer": None,
            "file_offer": None,
            "file_download": None,
            "map_card": None,
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
            pending_context=result.get("next_pending_context"),
            intent=result.get("intent"),
            topic=result.get("topic"),
            source=result.get("source"),
            source_file=result.get("source_file"),
            rewritten_query=result.get("rewritten_query"),
        )


agent_graph = AgentGraph()
