"""서버 설정 조회 (읽기 전용).

관리자 화면 '서비스 설정' 탭이 쓰는 라우터. 서버가 지금 무엇으로 답변을 만들고
어느 컬렉션을 보고 있는지 확인만 한다 — 값을 바꾸는 엔드포인트는 두지 않는다
(설정 변경은 .env + 재기동이며, 화면에서 바꾸면 컨테이너 재시작 시 되돌아간다).

모듈명이 service.py였는데 엔드포인트(/settings)·프론트(api/admins/settings.js)·
화면 메뉴와 이름이 모두 어긋나 settings.py로 맞췄다. 같은 폴더의 다른 라우터들도
전부 '다루는 대상' 이름을 쓴다(rag · faq · files · chats · departments …).
"""
from fastapi import APIRouter

from app.schemas.admins import SettingsResponse
from app.services.admin_service import admin_service

router = APIRouter()


@router.get("/settings", response_model=SettingsResponse, summary="서버 설정 조회")
async def get_settings():
    return admin_service.get_settings()
