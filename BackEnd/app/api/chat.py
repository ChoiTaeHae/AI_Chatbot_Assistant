from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
import traceback

from app.schemas.chat import ChatRequest, ChatResponse, FeedbackRequest, RewriteFeedbackRequest
from app.core.Database import get_db
from app.core.deps import get_current_user
from app.core.rate_limit import chat_rate_limit_optional
from app.models.DB_Table import Student
from app.services.chat_service import chat_service

router = APIRouter()


# 채팅만 비로그인을 허용한다. 학사 문서·일정·학식·지도는 누가 물어도 답이 같으므로
# 로그인을 요구할 이유가 없다. 개인 데이터가 필요한 질문(성적·졸업요건·장학금 설문)은
# 핸들러에서 로그인 안내로 돌려준다 — 라우터에서 통째로 막으면 나머지까지 못 쓴다.
# 아래 세션·피드백 엔드포인트는 그대로 로그인 필수(저장된 개인 대화를 다루므로).
@router.post("/chat", response_model=ChatResponse, summary="AI 챗봇 질문 (비로그인 가능)")
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student | None = Depends(chat_rate_limit_optional),
):
    try:
        return await chat_service.create_chat_response(request, db, current_user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception:
        # 내부 예외 문구를 그대로 내보내지 않는다. 이 엔드포인트는 비로그인으로도
        # 열려 있어 응답이 누구에게나 보인다. 실측(2026-08-19): Vertex 404 메시지가
        # GCP 프로젝트 ID를 그대로 노출했다. DB 오류면 테이블·컬럼명이, Qdrant 오류면
        # 클러스터 주소가 같은 경로로 새어 나간다.
        # 원인 추적에 필요한 전문은 아래 print_exc()로 서버 로그에만 남긴다.
        traceback.print_exc()
        raise HTTPException(
            status_code=503,
            detail="AI 서비스에 일시적인 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.",
        )


@router.get("/chat/sessions", summary="내 최근 대화 목록 (사이드바)")
async def my_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    return await chat_service.get_my_sessions(db, current_user)


@router.get("/chat/sessions/{session_id}", summary="과거 대화 다시 열기")
async def my_session_messages(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await chat_service.get_my_session_messages(db, session_id, current_user)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/chat/sessions/{session_id}", summary="대화 삭제 (soft delete)")
async def delete_my_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await chat_service.delete_my_session(db, session_id, current_user)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/chat/feedback", summary="답변 피드백 (좋아요/싫어요)")
async def chat_feedback(
    request: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await chat_service.save_feedback(request, db, current_user)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="피드백을 저장하지 못했습니다.")


@router.post("/chat/rewrite-feedback", summary="[개발용] rewrite 피드백 (파인튜닝 라벨)")
async def rewrite_feedback(
    request: RewriteFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Student = Depends(get_current_user),
):
    try:
        return await chat_service.save_rewrite_feedback(request, db, current_user)
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="피드백을 저장하지 못했습니다.")
