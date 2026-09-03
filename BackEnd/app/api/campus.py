"""
캠퍼스 지도 이미지 프록시

Kakao Static Map API를 서버에서 호출하고 이미지를 반환.
API 키가 프론트에 노출되지 않도록 백엔드에서 중개.
"""
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.core.config import settings

router = APIRouter()

KAKAO_STATIC_MAP_URL = "https://dapi.kakao.com/v2/maps/staticmap.png"


@router.get("/campus/map-image", summary="캠퍼스 정적 지도 이미지")
async def get_map_image(
    lat: float = Query(..., description="위도"),
    lng: float = Query(..., description="경도"),
    w: int   = Query(360, description="이미지 너비"),
    h: int   = Query(200, description="이미지 높이"),
    level: int = Query(3, description="지도 확대 레벨 (1=최대, 14=최소)"),
):
    if not settings.KAKAO_API_KEY:
        raise HTTPException(status_code=503, detail="Kakao API 키가 설정되지 않았습니다.")

    params = urllib.parse.urlencode({
        "appkey": settings.KAKAO_API_KEY,
        "center": f"{lng},{lat}",
        "level":  level,
        "marker": f"color,red,{lng},{lat}",
        "w":      w,
        "h":      h,
    })
    url = f"{KAKAO_STATIC_MAP_URL}?{params}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            image_bytes = resp.read()
            content_type = resp.headers.get("Content-Type", "image/png")
        return Response(content=image_bytes, media_type=content_type)
    except Exception:
        # 이 엔드포인트는 인증 없이 열려 있다. urllib 예외 문구에는 호출한 카카오 URL과
        # 질의 파라미터가 그대로 들어가므로 클라이언트에 내보내지 않는다.
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=502, detail="지도 이미지를 불러오지 못했습니다.")
