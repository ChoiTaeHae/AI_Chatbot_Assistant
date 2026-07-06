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

_BUILDING_CODE_RE = re.compile(r'^[WwEeSs]\d{1,2}$')

# 파일 제안 관련 긍정 표현 키워드
# ⚠️ 단어 단위 매칭을 하므로 부분 문자열에는 걸리지 않음
POSITIVE_KEYWORDS = {
    # 기본 긍정
    "응", "네", "예", "응응", "네네", "웅", "웅웅", "넵", "넹", "ㅇㅇ",
    # 파일 요청
    "줘", "줘요", "줘봐", "내놔", "주세요", "보내줘", "보내줘요", "보내주세요", "부탁해", "부탁해요",
    # 긍정 동의
    "좋아", "좋아요", "알겠어", "알겠습니다", "그래", "그래요", "그럼", "그럼요",
    "당연", "물론", "당근", "맞아", "맞아요",
    # 영어/인터넷
    "오케", "오케이", "ok", "OK", "Ok", "ㅇㅋ",
    # 필요 표현
    "원해요", "필요해요", "필요합니다", "필요해", "원해",
}

# 파일 거절 키워드
NEGATIVE_KEYWORDS = {
    # 명확한 부정
    "아니", "아니요", "아니다", "아니에요", "아닙니다",
    "no", "No", "NO", "ㄴㄴ",
    # 거절 표현
    "됐어", "됐습니다", "안해도돼", "안할래",
    "싫어", "싫어요", "싫습니다", "별로", "별로야",
    "괜찮아", "괜찮아요", "괜찮습니다",
    "필요없어", "필요없어요", "필요없습니다",
    "안받을게", "안받아도돼", "그만", "그만해요", "패스",
}

QUESTION_KEYWORDS = ["어떻게", "언제", "뭐야", "뭔데", "왜", "어디", "?", "？", "알려", "설명", "궁금", "뭐가", "뭐레", "가능해", "어떤"]


def _is_campus_question(q: str) -> bool:
    return bool(_BUILDING_CODE_RE.search(q))


def _is_confirmation(text: str) -> bool:
    """단어 단위 매칭으로 긍정 표현 확인.
    '하고' 안의 '고'처럼 부분 문자열로는 걸리지 않는다.
    """
    # 질문 표현이 있으면 새 질문으로 판단
    if any(kw in text for kw in QUESTION_KEYWORDS):
        return False
    # 공백 기준 단어 분리 후 정확히 일치하는 키워드만 체크
    tokens = set(text.split())
    return bool(tokens & POSITIVE_KEYWORDS)


def _is_rejection(text: str) -> bool:
    """단어 단위 매칭으로 거절 표현 확인."""
    tokens = set(text.split())
    return bool(tokens & NEGATIVE_KEYWORDS)




def _filter_files_by_question(files: list[str], question: str) -> list[str]:
    """
    질문에 등장하는 파일명 핵심 키워드를 기준으로 관련 파일만 필터링.

    예: 질문 "자퇴하려면" → "자퇴" 유일 파일만 반환 (휴학/복학 제외)
    매칭 파일 없으면 전체 반환 (폴백).
    """
    if not question or len(files) <= 1:
        return files

    q_flat = question.replace(" ", "").replace("_", "")
    matched = []

    for f in files:
        stem = Path(f).stem.replace(" ", "").replace("_", "")
        found = False
        # 파일명의 부분 문자열을 긴 것부터 체크 (2자 이상)
        for length in range(len(stem), 1, -1):
            for start in range(len(stem) - length + 1):
                chunk = stem[start:start + length]
                if chunk in q_flat:
                    found = True
                    break
            if found:
                break
        if found:
            matched.append(f)

    # 매칭 파일 있으면 필터링된 목록, 없으면 전체 반환
    return matched if matched else files


def _with_file_offer(updates: dict, topic: str, question: str = "") -> dict:
    files = AVAILABLE_FILES.get(topic, [])
    if not files:
        return updates

    # 질문 기반 관련 파일만 필터링
    files = _filter_files_by_question(files, question)

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

    # pending_context(팀원 멀티턴)가 활성 중이면 파일 체크를 건너뜀
    # → 팀원 로직이 우선순위를 가짐
    if pf and not state.get("pending_context"):
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
    """임베딩 유사도 기반 분류 — (topic_name, handler_type, score, all_scores) 사용"""
    loop = asyncio.get_event_loop()
    try:
        topic_name, handler_type, score, all_scores = await loop.run_in_executor(
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

        # topic이 바뀌는 경우: 새 topic이 이전 topic보다 확실히 우세할 때만 전환
        # (절대 점수 기준은 애매한 후속 질문과 명확한 주제 전환을 구분 못 함)
        prev_score = all_scores.get(prev_topic) if prev_topic else None
        if prev_topic and topic_name != prev_topic and prev_score is not None:
            if score - prev_score < _SWITCH_MARGIN:
                prev_info = topic_router._proto_vecs.get(prev_topic, {})
                prev_handler = prev_info.get("handler_type", "rag")
                print(
                    f"[Graph] topic 전환 우세 미달 (새 {topic_name}={score:.3f} vs "
                    f"이전 {prev_topic}={prev_score:.3f}, 차이 {score - prev_score:.3f} < {_SWITCH_MARGIN})"
                    f" → 이전 topic 유지"
                )
                return {"intent": prev_handler, "topic": prev_topic, "confidence": score}
            print(
                f"[Graph] topic 전환 승인 (새 {topic_name}={score:.3f} vs "
                f"이전 {prev_topic}={prev_score:.3f}, 차이 {score - prev_score:.3f} ≥ {_SWITCH_MARGIN})"
            )

        # 새 topic에 문서가 하나도 없으면 전환 취소 → 이전 topic 유지
        # (빈 topic 전환 → 검색 0건 → 환각 답변으로 이어지는 함정 방지)
        if prev_topic and topic_name != prev_topic:
            try:
                doc_count = await loop.run_in_executor(
                    None, rag_service.vector_store.count_by_topic, topic_name
                )
                if doc_count == 0:
                    prev_info = topic_router._proto_vecs.get(prev_topic, {})
                    prev_handler = prev_info.get("handler_type", "rag")
                    print(f"[Graph] '{topic_name}' 문서 0개 → 전환 취소, 이전 topic '{prev_topic}' 유지")
                    return {"intent": prev_handler, "topic": prev_topic, "confidence": score}
            except Exception as e:
                print(f"[Graph] topic 문서 수 확인 실패 (전환 진행): {e}")

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
    }, metadata.get("topic") or "scholarship", state["question"])


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
        "rewritten_query": metadata.get("rewritten_query"),
    }, topic, state["question"])


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
