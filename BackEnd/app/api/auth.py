# from fastapi import APIRouter, Depends, HTTPException
# from sqlalchemy.ext.asyncio import AsyncSession

# from app.core.Database import get_db
# from app.schemas.chat import ChatRequest

# router = APIRouter()


# @router.post("/chat")
# async def chat(request: ChatRequest, db: AsyncSession = Depends(get_db)):
#     # TODO: LLM 연동
#     return {"answer": f"질문을 받았습니다: {request.question}"}
