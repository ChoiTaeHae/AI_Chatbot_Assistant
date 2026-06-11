import asyncio
import json
import re
import urllib.parse
import urllib.request

from sqlalchemy import String, cast, or_, select

from app.core.Database import AsyncSessionLocal
from app.core.config import settings
from app.models.DB_Table import Building, Room
from app.services.chat_service import chat_service


KAKAO_KEYWORD_SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
CAMPUS_KEYWORD = "우송대학교"

LOCATION_NOT_FOUND = (
    "요청하신 위치를 찾지 못했습니다. "
    "건물명, 학과명, 강의실 번호를 조금 더 정확하게 입력해주세요. "
    "예: 우송도서관, 학생회관, 공학관, 401호"
)

REMOVE_WORDS = [
    "어디",
    "어딨어",
    "어디야",
    "위치",
    "위치는",
    "알려줘",
    "알려주세요",
    "찾아줘",
    "찾아주세요",
    "가는",
    "가려면",
    "어떻게",
    "있어",
    "있나요",
    "건물",
    "건물이",
    "어디임",
    "가야돼",
    "가야해",
    "몇층",
    "몇 층",
]


# 건물 코드 추출 (w15가 → W15)
_CODE_EXTRACT_RE = re.compile(r'^[WwEeSs]\d{1,2}')

# 한국어 조사 제거: "크로톤빌은" → "크로톤빌", "동캠퍼스의" → "동캠퍼스"
# 긴 조사를 먼저 배치해야 올바르게 제거됨 (에서 > 에, 으로 > 로)
_KO_PARTICLE_RE = re.compile(
    r'(에서|으로|이라고|이라|라고|에게|부터|까지|처럼|만큼|보다|은|는|이|가|을|를|의|에|로|와|과|도|만|요)$'
)


def _normalize_text(text: str) -> str:
    text = text.strip()
    text = re.sub(r"[^\w가-힣\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _strip_particles(token: str) -> str:
    """한국어 조사를 제거한 형태 반환. 변화 없으면 원본 반환."""
    return _KO_PARTICLE_RE.sub('', token)


def _make_keyword_candidates(question: str) -> list[str]:
    normalized = _normalize_text(question)
    cleaned = normalized

    for word in REMOVE_WORDS:
        cleaned = cleaned.replace(word, " ")

    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    candidates: list[str] = []

    room_matches = re.findall(r"\d+\s*호", normalized)
    candidates.extend(room_matches)

    if cleaned:
        candidates.append(cleaned)

    tokens = [token for token in cleaned.split() if len(token) >= 2]
    candidates.extend(tokens)

    # 조사 제거 버전도 후보에 추가
    # 예: "크로톤빌은" → "크로톤빌", "동캠퍼스의" → "동캠퍼스"
    for token in tokens:
        stripped = _strip_particles(token)
        if stripped != token and len(stripped) >= 2:
            candidates.append(stripped)

    if normalized and normalized not in candidates:
        candidates.append(normalized)

    unique_candidates: list[str] = []

    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in unique_candidates:
            unique_candidates.append(candidate)

    # 건물 코드(w15, w15가 어디야 등) → 대문자 코드(W15)를 앞에 추가
    # re.match로 토큰 앞부분에서 코드를 추출하므로 'w15가' 같은 혼합 토큰도 처리
    result: list[str] = []
    for c in unique_candidates:
        m = _CODE_EXTRACT_RE.match(c)
        if m:
            upper = m.group().upper()   # 'w15가' → 'W15'
            if upper not in result:
                result.append(upper)
        if c not in result:
            result.append(c)

    return result


async def _extract_location_keyword(question: str) -> str | None:
    prompt = (
        "사용자의 질문에서 대학교 캠퍼스 건물명, 장소명, 학과명, 강의실 번호 중 "
        "위치 검색에 가장 중요한 키워드 하나만 추출하세요.\n"
        "설명하지 말고 키워드 하나만 답하세요.\n"
        "위치 키워드가 없으면 '없음'이라고 답하세요.\n\n"
        f"질문: {question}\n"
        "키워드:"
    )

    try:
        keyword = await chat_service.answer(prompt)
    except Exception as e:
        print(f"[LOCATION] 키워드 추출 실패: {e}")
        return None

    keyword = _normalize_text(keyword)
    keyword = keyword.replace("키워드", "").replace(":", "").strip()

    if not keyword or keyword == "없음":
        return None

    return keyword.splitlines()[0].strip()


async def _search_db_building_only(keyword: str) -> tuple[Building | None, None]:
    async with AsyncSessionLocal() as db:
        building_result = await db.execute(
            select(Building).where(
                or_(
                    Building.name.ilike(f"%{keyword}%"),
                    Building.address.ilike(f"%{keyword}%"),
                    cast(Building.aliases, String).ilike(f"%{keyword}%"),
                )
            )
        )
        building = building_result.scalars().first()
        return building, None


async def _search_db_with_room(keyword: str) -> tuple[Building | None, Room | None]:
    async with AsyncSessionLocal() as db:
        room_result = await db.execute(
            select(Building, Room)
            .join(Room, Room.building_id == Building.id)
            .where(
                or_(
                    Room.room_no.ilike(f"%{keyword}%"),
                    Room.note.ilike(f"%{keyword}%"),
                    Building.name.ilike(f"%{keyword}%"),
                )
            )
        )
        room_match = room_result.first()
        if room_match:
            return room_match[0], room_match[1]

        building_result = await db.execute(
            select(Building).where(
                Building.name.ilike(f"%{keyword}%")
            )
        )
        building = building_result.scalars().first()
        return building, None


async def _find_location_from_question(question: str) -> tuple[Building | None, Room | None, str | None]:
    candidates = _make_keyword_candidates(question)

    # 질문에 호실 번호 있는지 먼저 확인
    has_room = bool(re.findall(r"\d+\s*호", question))

    for keyword in candidates:
        if has_room:
            building, room = await _search_db_with_room(keyword)
        else:
            building, room = await _search_db_building_only(keyword)

        if building:
            return building, room, keyword

    extracted_keyword = await _extract_location_keyword(question)
    if extracted_keyword and extracted_keyword not in candidates:
        if has_room:
            building, room = await _search_db_with_room(extracted_keyword)
        else:
            building, room = await _search_db_building_only(extracted_keyword)
        if building:
            return building, room, extracted_keyword

    return None, None, None


def _call_kakao_keyword_api(query: str) -> dict | None:
    params = urllib.parse.urlencode({"query": query, "size": 5})
    url = f"{KAKAO_KEYWORD_SEARCH_URL}?{params}"

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"KakaoAK {settings.KAKAO_API_KEY}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
            return json.loads(body)
    except Exception as e:
        print(f"[LOCATION] Kakao Local API 호출 실패: {e}")
        return None


async def _search_kakao_place(building: Building) -> dict | None:
    # DB에 저장된 place_url에서 Kakao place ID 추출
    # 예: https://place.map.kakao.com/17561317 → "17561317"
    target_id = None
    if building.place_url:
        m = re.search(r'/(\d+)$', building.place_url)
        if m:
            target_id = m.group(1)

    queries = [
        f"{CAMPUS_KEYWORD} {building.name}",  # "우송대학교 식품건축관"
        str(building.name),                    # "식품건축관"
    ]

    for query in queries:
        data = await asyncio.to_thread(_call_kakao_keyword_api, query)
        if not data:
            continue
        documents = data.get("documents", [])

        for doc in documents:
            if target_id and target_id in doc.get("place_url", ""):
                return doc

    return None


def _build_target_payload(building: Building, room: Room | None) -> dict:
    payload = {
        "building_name": building.name,
        "address": building.address,
        "place_url": building.place_url,
    }

    if room:
        payload.update(
            {
                "room_no": room.room_no,
                "floor": room.floor,
                "note": room.note,
            }
        )

    return payload


def _build_map_card(building: Building, place: dict | None) -> dict:
    address = building.address
    place_url = building.place_url

    if place:
        address = place.get("road_address_name") or place.get("address_name") or address
        place_url = place.get("place_url") or place_url

    map_card = {
        "provider": "kakao",
        "title": building.name,
        "address": address,
        "place_url": place_url,
        "source": "kakao_local" if place else "database",
    }

    if place:
        map_card.update(
            {
                "latitude": float(place["y"]),
                "longitude": float(place["x"]),
            }
        )

    return map_card


def _build_answer(building: Building, room: Room | None) -> str:
    if room:
        return f"{building.name} {room.floor}층 {room.room_no} 위치를 찾았습니다. 지도에서 건물 위치를 확인해보세요."

    return f"{building.name} 위치를 찾았습니다. 지도에서 확인해보세요."


async def answer_location_question(question: str) -> dict:
    print("[LOCATION] 위치 검색 시작")

    building, room, matched_keyword = await _find_location_from_question(question)

    if not building:
        return {
            "type": "location",
            "found": False,
            "answer": LOCATION_NOT_FOUND,
            "matched_keyword": matched_keyword,
            "target": None,
            "map_card": None,
        }

    place = await _search_kakao_place(building)
    map_card = _build_map_card(building, place)

    # place_url이 있으면 found: True — 좌표 없어도 카카오맵 링크로 위치 확인 가능
    # (DB에 저장된 place_url이 있는 한 항상 True)
    has_info = bool(map_card.get("place_url") or
                    (map_card.get("latitude") and map_card.get("longitude")))

    if not has_info:
        return {
            "type": "location",
            "found": False,
            "answer": f"{building.name} 위치 정보를 가져오지 못했습니다.",
            "matched_keyword": matched_keyword,
            "target": _build_target_payload(building, room),
            "map_card": None,
        }

    return {
        "type": "location",
        "found": True,
        "answer": _build_answer(building, room),
        "matched_keyword": matched_keyword,
        "target": _build_target_payload(building, room),
        "map_card": map_card,
    }


class CampusService:
    @staticmethod
    async def answer_location_question(question: str) -> dict:
        return await answer_location_question(question)

    @staticmethod
    async def search_location(question: str) -> dict:
        return await answer_location_question(question)
