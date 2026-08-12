import asyncio
import json
import re
import urllib.parse
import urllib.request

from sqlalchemy import String, cast, or_, select

from app.core.Database import AsyncSessionLocal
from app.core.config import settings
from app.models.DB_Table import Building, Room, BuildingContact, Office
from app.services.llm_service import llm_service
from app.prompts import KEYWORD_EXTRACTION_SYSTEM_PROMPT


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
        keyword = await llm_service.answer(
            prompt, max_tokens=32, system_prompt=KEYWORD_EXTRACTION_SYSTEM_PROMPT
        )
    except Exception as e:
        print(f"[LOCATION] 키워드 추출 실패: {e}")
        return None

    keyword = _normalize_text(keyword)
    keyword = keyword.replace("키워드", "").replace(":", "").strip()

    if not keyword or keyword == "없음":
        return None

    return keyword.splitlines()[0].strip()


def _norm_alias(s) -> str:
    return str(s or "").replace(" ", "").lower()


def _prefer_exact(buildings: list[Building], keyword: str) -> Building | None:
    """이름/별칭이 keyword와 '정확히' 일치하는 건물을 부분일치보다 우선한다.

    부분일치(ilike %kw%)만 쓰면 '학생회관'이 '학생회관(동캠)'·'학생회관(서캠)' 두 이름에 모두
    걸려 .first()가 임의로 하나를 집는다. 그러나 별칭을 정확히 '학생회관'으로 둔 건물(서캠)이
    의도된 답이다. → 이름 또는 별칭이 keyword와 완전히 같은 건물을 먼저 고르고,
    없을 때만 기존처럼 첫 부분일치 결과를 쓴다. (공백·대소문자 무시하고 비교)"""
    if not buildings:
        return None
    kw = _norm_alias(keyword)
    for b in buildings:
        if any(_norm_alias(n) == kw for n in [b.name, *(b.aliases or [])]):
            return b
    return buildings[0]


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
        building = _prefer_exact(list(building_result.scalars().all()), keyword)
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
        building = _prefer_exact(list(building_result.scalars().all()), keyword)
        return building, None


async def building_hit_alias(question: str) -> str | None:
    """has_building_hit과 같은 판정을 하되, 매칭된 '별칭 문자열'을 돌려준다.

    라우팅에서 "질문이 건물명만 덩그러니 있는 것인지"를 판단하려면 어떤 말이 건물로
    잡혔는지 알아야 한다. (예: '기숙사 입사 제한 대상은?'에서 잡힌 건 '기숙사'뿐이고
    나머지 '입사 제한 대상'은 위치와 무관한 내용어 → 지도가 아니라 정보 질문)
    """
    cands = {_norm_alias(c) for c in _make_keyword_candidates(question) if _norm_alias(c)}
    if not cands:
        return None
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Building.name, Building.aliases))).all()
    for name, aliases in rows:
        tokens = {_norm_alias(name), _norm_alias(re.sub(r"\s*\([^)]*\)", "", str(name)))}
        tokens |= {_norm_alias(a) for a in (aliases or [])}
        matched = cands & {t for t in tokens if t}
        if matched:
            return max(matched, key=len)     # 가장 구체적인 별칭
    return None


async def has_building_hit(question: str) -> bool:
    """LLM 없이(후보 토큰 기반) 질문이 '특정 건물을 지칭'하는지 빠르게 확인한다.

    라우팅 fast-path 전용 — 건물명이 있으면(위치 의도거나 정보의도 없음일 때) campus로 보낸다.

    ★ substring(ilike %kw%)이 아니라 '정확 일치'로 판정한다. substring이면 '학생'(주어)이
      '유학생기숙사'·'학생회관'에 걸려 "학생이 주차장정기권 살 수 있나?"가 건물 질문으로
      오판됐다. 건물의 짧은 통칭(도서관·체육관·학군단…)은 모두 정확한 별칭으로 등록돼 있어
      정확 일치만으로 충분하다. (이름/괄호뗀이름/별칭을 공백·대소문자 무시하고 비교)"""
    cands = {_norm_alias(c) for c in _make_keyword_candidates(question) if _norm_alias(c)}
    if not cands:
        return False
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(Building.name, Building.aliases))).all()
    for name, aliases in rows:
        tokens = {_norm_alias(name), _norm_alias(re.sub(r"\s*\([^)]*\)", "", str(name)))}
        tokens |= {_norm_alias(a) for a in (aliases or [])}
        if cands & {t for t in tokens if t}:
            return True
    return False


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
    # 이름의 '(서캠)'·'(동캠)' 같은 괄호 접미사는 카카오가 인식 못 해 검색이 0건이 된다
    # (실측: '우송대학교 학생회관(서캠)'→0건 / '우송대학교 학생회관'→5건, target_id 매칭 성공).
    # 괄호를 떼고도 검색한다. 결과에 두 캠퍼스가 섞여도 아래 target_id 매칭이 정확히 걸러낸다.
    bare = re.sub(r"\s*\([^)]*\)", "", str(building.name)).strip()
    if bare and bare != str(building.name):
        queries += [f"{CAMPUS_KEYWORD} {bare}", bare]

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


async def _get_building_contacts(building_id: int) -> list[dict]:
    """건물에 연결된 행정부서 연락처 목록 반환."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Office.name, Office.phone)
            .join(BuildingContact, BuildingContact.office_id == Office.id)
            .where(BuildingContact.building_id == building_id)
        )
        return [{"name": row.name, "phone": row.phone} for row in result.all()]


def _build_answer(building: Building, room: Room | None, contacts: list[dict]) -> str:
    if room:
        answer = f"{building.name} {room.floor}층 {room.room_no} 위치를 찾았습니다. 지도에서 건물 위치를 확인해보세요."
    else:
        answer = f"{building.name} 위치를 찾았습니다. 지도에서 확인해보세요."

    if contacts:
        lines = "\n".join(
            f"- {c['name']}: {c['phone']}" if c.get('phone') else f"- {c['name']}"
            for c in contacts
        )
        # '담당 부서'만 적으면 번호가 왜 여기 붙었는지 알 수 없어 뜬금없이 읽힌다.
        # 실측: '학생회관 어디야?'에 근로장학금·국가장학금 번호가 설명 없이 나왔다 —
        # 위치를 물었는데 장학금 번호가 뜨니 관련 없는 정보로 보인다.
        # 이 건물에서 그 업무를 처리한다는 관계를 한 줄로 밝혀 준다.
        answer += f"\n\n📞 이 건물에서 처리하는 업무입니다. 문의는 아래로 해주세요.\n{lines}"

    return answer


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
    contacts = await _get_building_contacts(building.id)

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
        "answer": _build_answer(building, room, contacts),
        "matched_keyword": matched_keyword,
        "target": _build_target_payload(building, room),
        "map_card": map_card,
        "contacts": contacts,
    }


class CampusService:
    @staticmethod
    async def answer_location_question(question: str) -> dict:
        return await answer_location_question(question)

    @staticmethod
    async def search_location(question: str) -> dict:
        return await answer_location_question(question)
