import asyncio
import math
import re

from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.rag.Retrieval.retriever import MAX_TOTAL_CONTEXT   # 보강 블록도 같은 예산 안에서 다룬다
from app.prompts import RAG_GENERAL_PROMPT, RAG_CLUB_LIST_PROMPT, RAG_CLUB_DETAIL_PROMPT, QUERY_REWRITE_PROMPT, QUERY_REWRITE_WITH_CONTEXT_PROMPT, KEYWORD_EXTRACTION_SYSTEM_PROMPT, SYSTEM_PROMPT

# 재작성 드리프트 임계값 — 원문과 재작성의 의미 유사도가 이 값 미만이면
# 환각(엉뚱한 주제로 변형)으로 보고 원본 질문을 사용한다. (bge-m3 코사인, 튜닝 가능)
_REWRITE_DRIFT_THRESHOLD = 0.5


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def _is_semantic_drift(original: str, rewritten: str) -> bool:
    """재작성 결과가 원문과 의미상 너무 멀어졌는지(환각) 임베딩 유사도로 판단."""
    try:
        loop = asyncio.get_event_loop()
        vecs = await loop.run_in_executor(
            None, rag_service.embedding.embed_texts, [original, rewritten]
        )
        sim = _cosine(vecs[0], vecs[1])
        print(f"[RAG_GENERAL] 재작성 의미 유사도={sim:.3f} (임계 {_REWRITE_DRIFT_THRESHOLD})")
        return sim < _REWRITE_DRIFT_THRESHOLD
    except Exception as e:
        # 검사 실패 시 재작성을 막지 않음 (검색 자체를 못하는 것보단 나음)
        print(f"[RAG_GENERAL] 드리프트 검사 실패(무시): {e}")
        return False


# 주제를 식별하지 못하는 일반어 — 아래 주제어 검사에서 제외한다.
# (접두 일치로 비교하므로 '얼마야'는 '얼마', '신청은'은 '신청'으로 걸러진다)
_GENERIC_TERMS = (
    "신청", "방법", "알려줘", "어떻게", "언제", "얼마", "기간", "일정", "안내", "문의",
    "절차", "서류", "가능", "필요", "준비", "무엇", "무슨", "어디", "해줘", "되나요",
    # '제출'은 행위지 주제가 아니다. 어미를 떼는 로직이 생기면서 '제출해야해?' → '제출해야'가
    # 주제어로 잡혀 맥락 통합('언제까지 제출?' + 이전 휴학)이 폐기됐다(실측).
    # 실제 질문 2300건 검사 결과 사라지는 건 '제출/제출해/제출해야' 등 활용형뿐이라 안전하다.
    "제출",
    "인가요", "있어", "있나요", "하나요", "까지", "부터", "궁금", "확인", "조건", "기준",
    "대해서", "관련", "이야", "이에요", "예요",
    # 속성어 — 주제가 아니라 '주제의 한 속성'을 묻는 말이라 주제어가 아니다.
    # ('기숙사비 얼마야' 다음의 '비용 얼마야'가 주제어를 가진 새 질문으로 오인되면,
    #  이전 주제(기숙사)를 못 붙여 맥락 통합이 깨진다.) 실제 질문 2061건에서 진짜 주제어를
    #  삼키지 않음을 확인한 것만 넣는다. '시간'(→시간표)·'자격'(→자격증)은 접두 일치로
    #  다른 단어를 통째로 먹어 제외했다.
    "비용", "금액", "가격", "요금", "위치", "장소", "대상", "연락처", "번호",
    "종류", "이름", "내용", "전화번호", "홈페이지", "주소",
    # 지시대명사 — 이전 주제를 가리키는 말이라 주제어가 아니다("그건 얼마야?")
    "그건", "그거", "그것", "이건", "이거", "이것", "저건", "저거", "저것",
    "거기", "여기", "그때", "그럼", "그러면",
)
# 서술어(동사·형용사) 어미 — 주제어가 아니므로 제외한다.
# 예: '내야해'(언제까지 내야해?)를 주제어로 오인하면 정상적인 맥락 보충까지 폐기된다.
# 주의: 이 목록은 _is_keyword_query(재작성 생략 판정)에서도 쓰인다. 명사 끝글자와 겹치면
# 멀쩡한 주제어가 서술어로 오인되므로(예: '지'를 넣으면 '복지'가 죽는다) 충돌 없는 것만 넣는다.
# '싶어'가 없어 '휴학 신청하고 싶어'가 검색어 형태로 오판됐던 실측을 반영해 보강했다.
_PREDICATE_SUFFIXES = (
    "해", "해요", "야해", "줘", "세요", "나요", "어요", "아요", "야", "다",
    "싶어", "싶다", "싶은", "싶은데", "할래", "될까", "되니", "하니", "인가요", "봐", "어때",
    # 의문 종결형은 '가요'처럼 뭉뚱그리면 명사와 부딪히므로 정확형만 넣는다.
    # 여기서 놓쳐도 치명적이지 않다 — 원문으로 검색했다가 0건이면 지연 재작성이 구제한다.
    "뭔가요", "뭐예요", "뭐죠", "뭔데",
)
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")


def _distinctive_terms(question: str) -> list[str]:
    """질문에서 '주제를 식별하는' 토큰만 추출 (일반어·서술어 제외).

    비어 있으면 = 주제어 없는 모호한 후속 질문("기간은?") → 이전 맥락 보충이 정상이다.
    (애매하면 비우는 쪽이 안전 — 검사가 skip되어 재작성을 막지 않는다)"""
    terms = []
    for tok in _TOKEN_RE.findall(question or ""):
        if len(tok) < 2:
            continue
        if any(tok.startswith(g) for g in _GENERIC_TERMS):
            continue
        # 서술어 어미로 끝나면 어미만 떼고 앞부분(어간)을 본다. 토큰을 통째로 버리면
        # 띄어쓰기 없이 붙여 쓴 질문에서 주제어까지 사라진다 —
        # 실측: '기숙사비용얼마야?'가 토큰 하나('기숙사비용얼마야')라 끝의 '야' 때문에
        # 통째로 제외돼 주제어가 []가 됐고, 두 가드가 '주제어 없는 파편 질문'으로 오인해
        # 재작성이 이전 주제로 통째 교체된 것('공결 신청 방법')을 통과시켰다.
        suffix = next((s for s in _PREDICATE_SUFFIXES if tok.endswith(s)), None)
        if suffix:
            stem = tok[: -len(suffix)]
            # 어간이 너무 짧거나(우연) 그 자체가 일반어면 주제어로 인정하지 않는다.
            if len(stem) < 2 or any(stem.startswith(g) for g in _GENERIC_TERMS):
                continue
            terms.append(stem)
            continue
        terms.append(tok)
    return terms


# 동아리 문서 한 줄: "분야: 봉사 | 동아리명: 새말동아리 | 주요활동: ... | 설립: 1999.3"
_CLUB_LINE_RE = re.compile(r"분야:\s*(?P<cat>[^|]+?)\s*\|\s*동아리명:\s*(?P<name>[^|]+?)\s*\|\s*주요활동:\s*(?P<act>[^|]+?)\s*(?:\|\s*설립:.*)?$")
# 분야 표기 순서 고정 — LLM이 매번 순서·형식을 바꾸던 것을 코드로 못박는다.
_CLUB_CAT_ORDER = ["봉사", "교양", "예체능", "종교"]


def format_club_list(context: str) -> str:
    """동아리 목록을 '분야별 그룹 + 이름 : 설명' 형식으로 코드에서 직접 만든다.

    문서가 '분야: X | 동아리명: Y | 주요활동: Z' 로 완전히 정형화돼 있어 LLM이 정리할 게 없다.
    그런데 LLM에 맡기면 같은 질문에도 형식이 매번 달라졌다(글머리표 유무, 파이프 표 등) —
    입력(재작성→검색 컨텍스트)이 미세하게 바뀌면 temperature 0.0이어도 출력이 달라지기 때문.
    코드로 파싱·포맷하면 입력과 무관하게 항상 같은 형식이 나온다(schedule·graduation과 동일 원칙).
    파싱 실패 시 빈 문자열을 반환해 호출부가 LLM 폴백으로 넘어가게 한다.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    for raw in context.splitlines():
        m = _CLUB_LINE_RE.search(raw)
        if not m:
            continue
        cat = m.group("cat").strip()
        name = m.group("name").strip()
        act = re.sub(r"\s+", " ", m.group("act").strip())
        groups.setdefault(cat, [])
        if name not in [n for n, _ in groups[cat]]:      # 중복 청크 방지
            groups[cat].append((name, act))
    if not groups:
        return ""
    # 알려진 분야를 먼저, 그 외 분야는 등장 순서로 뒤에
    cats = [c for c in _CLUB_CAT_ORDER if c in groups] + [c for c in groups if c not in _CLUB_CAT_ORDER]
    blocks = []
    for c in cats:
        lines = "\n".join(f"- {name} : {act}" for name, act in groups[c])
        blocks.append(f"[{c}]\n{lines}")
    return "우송대학교 중앙동아리 목록입니다.\n\n" + "\n\n".join(blocks)


def _is_keyword_query(question: str) -> bool:
    """이미 검색어 형태인가 — 재작성해서 얻을 게 없고 훼손 위험만 있는 질문.

    재작성의 임무는 (1) 구어체 정리 (2) 동의어 치환인데, 순수 명사구는 (1)이 할 일이 없고
    (2)는 검색어 딕셔너리가 더 안전하게 한다(대체가 아닌 추가 + 점수 검증 + 결정론적).
    반면 손실은 크다 — 실측에서 'F스포렉스'가 두 번 서로 다르게 망가졌다:
      'F스포렉스 신청 방법'  → 근거에 없는 절차·기한을 LLM이 발명
      'F스포츠 학점 인정 졸업' → 고유명사 자체가 훼손
    위험이 대칭이 아니라(스킵=검색이 약해짐 / 훼손=틀린 말이 됨) 호출을 아예 안 하는 쪽이 낫다.

    단, 여기서 걸러도 검색이 0건이면 뒤에서 '지연 재작성'으로 다시 시도하므로,
    정말 용어 매핑이 필요한 질문은 구제된다.
    """
    toks = _TOKEN_RE.findall(question or "")
    if not toks or len(toks) > 3:
        return False
    # 구어체 어미가 있으면 정리할 거리가 있다 ('학칙 알려줘' → '학칙 규정')
    if any(t.endswith(s) for t in toks for s in _PREDICATE_SUFFIXES):
        return False
    # 주제어가 없으면 모호한 후속 질문('기간은?')이라 이전 맥락 통합이 필요하다
    return bool(_distinctive_terms(question))


# 재작성이 새로 만들어 내면 안 되는 '행위' 개념.
#
# 실측: 'F스포렉스'(헬스장·수영장 시설 이름)가 'F스포렉스 신청 방법'으로 재작성되자,
# 검색은 얇게(173자) 맞았고 LLM이 신청 대상·자격 요건·구비서류·"매월 15일까지(연장 불가)"를
# 통째로 지어냈다. 바로 다음 질문('F스포렉스에 대해서 알려줘')은 같은 문서로 정확히 답했다.
# → 질문 프레임이 근거에 없는 개념을 요구하면 8B는 빈칸을 메운다. 프롬프트에 이미
#   "문서에 없는 내용은 추측하지 않는다"가 있는데도 그랬다. 그래서 프레임 자체를 막는다.
#
# 값은 '원문에 그 개념이 있었다고 인정할 표현들'이다. 구어체를 넉넉히 넣어 둔 이유는,
# '어떻게' → '방법' 같은 구어체→공식용어 변환이 재작성의 본래 임무라 막으면 안 되기 때문.
# (넓게 인정할수록 가드가 관대해지므로 안전한 방향이다)
_ACTION_CONCEPTS: dict[str, tuple[str, ...]] = {
    # '어디서'도 방법을 묻는 씨앗으로 인정한다 — '증명서 어디서 떼' → '증명서 발급 방법'은
    # 정당한 변환인데 폐기됐다(실측). 반대로 '뭐야/얼마야'는 넣지 않는다: '졸업 요건 뭐야'가
    # '졸업 요건 확인 방법'이 되면 질문의 성격 자체가 바뀌므로 막아야 한다.
    "방법": ("방법", "어떻게", "어케", "하는법", "하려면", "어디"),
    "신청": ("신청", "접수", "지원", "넣", "내려"),
    "절차": ("절차", "과정", "순서", "어떻게", "하려면", "어디"),
    "발급": ("발급", "떼", "받"),
}


def _invents_action(question: str, rewritten: str, prev_question: str | None) -> str | None:
    """재작성이 원문·이전질문 어디에도 없던 '행위' 개념을 만들어 냈으면 그 개념명을 반환.

    이전 질문까지 근거로 인정한다 — 맥락 통합('언제까지 제출해야해?' + 이전 '휴학 어떻게
    신청해?' → '휴학 신청 서류 제출 기한')에서 '신청'은 이전 질문에서 온 정당한 개념이다.
    """
    src = f"{prev_question or ''} {question}".replace(" ", "")
    rw = (rewritten or "").replace(" ", "")
    for concept, aliases in _ACTION_CONCEPTS.items():
        if concept in rw and not any(a in src for a in aliases):
            return concept
    return None


# 주제어 어간 비교의 최소 길이 — 한 글자까지 줄이면 우연 일치로 주제 교체를 놓친다.
_STEM_MIN = 2


def _stem_in(term: str, text: str) -> bool:
    """주제어가 '어간 기준'으로 text에 있는지. 어미·조사가 붙어도 앞부분이 살아있으면 True.

    한국어 질문은 '공결신청하려면'처럼 주제어에 어미가 붙어 한 토큰이 되는 일이 잦다.
    통짜로 대조하면 '공결'로 정확히 줄인 재작성을 못 알아본다(실측: _keeps_topic이 좋은
    재작성을 폐기, _borrows_prev_topic이 공결 오염을 통과). 두 가드가 같은 규칙을 쓰도록
    여기로 모았다.
    """
    if not term or not text:
        return False
    for cut in range(len(term), _STEM_MIN - 1, -1):
        if term[:cut] in text:
            return True
    return False


def _borrows_prev_topic(question: str, rewritten: str, prev_question: str | None) -> str | None:
    """재작성이 '이전 질문에만 있던 주제어'를 현재 질문에 끌어붙였으면 그 단어를 반환.

    _keeps_topic은 현재 주제어가 '유지'됐는지만 본다. 그래서 유지하면서 '더하는' 경우를
    못 잡는다. 실측: '학칙 알려줘'(이전 '공결') → '공결 학칙'. '학칙'은 살아 있어 통과했지만
    엉뚱한 공결 문서로 검색됐다.

    구분 기준은 '현재 질문이 스스로 주제를 특정하는가'다(프롬프트에도 있는 규칙):
      - 현재 질문에 주제어가 없다  → 맥락 통합이 정상이다('언제까지 제출?' + 이전 '휴학...')
        → 이 함수는 None을 반환해 통과시킨다.
      - 현재 질문에 주제어가 있는데 이전 주제어까지 새로 붙었다 → 오염이다. 폐기한다.

    비교는 _stem_in()으로 한다. 토큰을 통째로 대조하면 어미가 붙어 붙임표기된 주제어를
    놓친다. 실측: 이전 '공결신청하려면 어떻게해?'의 주제어가 ['공결신청하려면'] 한 덩어리라,
    재작성 '공결 신청 방법 / 휴학 신청 방법'에 '공결'이 버젓이 있는데도 오염을 못 잡았다.
    """
    if not _distinctive_terms(question):
        return None                              # 주제어 없는 후속 → 맥락 통합 정상
    cur = question.replace(" ", "")
    rw = (rewritten or "").replace(" ", "")
    for t in _distinctive_terms(prev_question or ""):
        # 이전에만 있던 주제어(어간 기준)가 재작성에 끼어듦
        if _stem_in(t, rw) and not _stem_in(t, cur):
            return t
    return None


def _keeps_topic(question: str, rewritten: str) -> bool:
    """재작성이 현재 질문의 주제어를 하나라도 유지하는지.

    프롬프트에 '현재 질문에 뚜렷한 주제어가 있으면 이전 질문을 무시하라'는 규칙이 있지만
    8B가 자주 어겨 이전 주제로 통째로 갈아탄다(실측: '휴학 신청 방법'→'공결 신청 방법',
    '학칙 알려줘'→'수강신청 방법'). 임베딩 드리프트 가드는 기준문이 '이전+현재'라
    이 경우를 못 잡으므로, 주제어 유지 여부를 코드로 확정 검사한다.

    비교는 '어간 접두 일치'로 한다. 토큰을 통째로 대조하면 어미가 붙어 붙임표기된 주제어를
    놓친다 — 실측: '공결신청하려면 어떻게해?'의 주제어가 ['공결신청하려면'] 한 덩어리라,
    재작성 '공결 출석인정 신청 방법'(정확한 재작성)에 '공결'이 있는데도 폐기됐다. 그러면
    구어체 원본이 그대로 검색에 들어가 리랭커 점수가 무너진다(1등만 0.773, 2등부터 0.086).
    비교는 _borrows_prev_topic과 같은 _stem_in()을 쓴다(규칙 일원화)."""
    terms = _distinctive_terms(question)
    if not terms:
        return True                      # 모호한 후속 질문 → 검사 skip
    rw = (rewritten or "").replace(" ", "")
    return any(_stem_in(t, rw) for t in terms)


# ── 검색어 딕셔너리 ────────────────────────────────────────────────
# 학생이 쓰는 말 → 문서에 실제 존재하는 공식 용어.
# 문서에 없는 용어를 덧붙이면 오히려 검색이 망가지므로(실측: '간사 뽑는거 언제야'에
# '조교 모집'을 더하자 0.336 → 0.000) 점수로 검증된 매핑만 등록한다.
# DB(app_config, key="search_synonyms")에서 로드하며 아래는 시딩용 기본값.
DEFAULT_SEARCH_SYNONYMS: dict[str, list[str]] = {
    "학칙": ["학생규칙"],     # 실측 0.014 → 0.642
    "공결": ["출석인정"],     # 실측 0.051 → 0.994
}

_search_synonyms: dict[str, list[str]] = dict(DEFAULT_SEARCH_SYNONYMS)


def set_search_synonyms(mapping: dict | None) -> None:
    """DB 설정으로 딕셔너리를 런타임 교체. 값이 비면 기본값을 유지한다."""
    global _search_synonyms
    cleaned: dict[str, list[str]] = {}
    for key, val in (mapping or {}).items():
        term = str(key).strip()
        if not term:
            continue
        officials = [str(v).strip() for v in (val if isinstance(val, list) else [val]) if str(v).strip()]
        if officials:
            cleaned[term] = officials
    _search_synonyms = cleaned or dict(DEFAULT_SEARCH_SYNONYMS)
    print(f"[RAG_GENERAL] 검색어 딕셔너리 {len(_search_synonyms)}개 로드")


def expand_search_query(query: str) -> str:
    """질문에 구어 용어가 있으면 공식 용어를 뒤에 덧붙인다(치환이 아니라 추가).

    - 치환하지 않는 이유: 원 질문의 표현도 검색에 함께 반영되어야 안전하다.
    - 공식 용어가 이미 질문에 있으면 중복 추가하지 않는다.
    - 매핑이 없으면 원문 그대로 반환하므로 대부분의 질문에는 아무 영향이 없다.
    """
    if not query:
        return query
    qn = query.replace(" ", "")
    additions: list[str] = []
    for term, officials in _search_synonyms.items():
        if term.replace(" ", "") not in qn:
            continue
        for official in officials:
            if official.replace(" ", "") not in qn and official not in additions:
                additions.append(official)
    if not additions:
        return query
    expanded = f"{query} {' '.join(additions)}"
    print(f"[RAG_GENERAL] 검색어 확장: '{query}' → '{expanded}'")
    return expanded


def _clean_rewrite_output(raw: str | None) -> str:
    """LLM 재작성 출력 정리.
    - 빈/None 출력 안전 처리 (빈 문자열 반환)
    - 프롬프트 형식 에코 제거: LLM이 '… → 결과' 나 '이전 질문:… / 현재 질문:… → 결과'
      처럼 템플릿을 그대로 뱉는 경우 '→' 뒤(실제 결과)만 취한다.
    - 남은 '이전 질문:/현재 질문:/입력:/출력:' 접두 제거."""
    lines = [ln.strip() for ln in (raw or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    text = lines[0]
    for arrow in ("→", "->"):                 # 프롬프트 화살표 에코 → 뒤만
        if arrow in text:
            text = text.split(arrow)[-1].strip()
    for pref in ("이전 질문:", "현재 질문:", "입력:", "출력:"):
        if text.startswith(pref):
            text = text.split(":", 1)[1].strip()
    return text.strip()


async def _rewrite_query(question: str, prev_question: str | None = None, force: bool = False) -> str:
    """구어체 질문을 검색용 공식 용어로 변환.

    prev_question이 있으면(topic 유지된 후속 질문) 이전 질문의 주제어를 보충해
    재작성한다 — "기간은 얼마나 돼?"가 엉뚱한 검색어로 변환되는 것을 방지.

    force=True면 검색어 형태 판정을 건너뛴다 — '지연 재작성'(원문 검색이 0건이라 뒤늦게
    재작성을 시도하는 경로) 전용. 그때도 생략하면 아무 일도 일어나지 않는다."""
    # 이미 검색어 형태면 재작성이 얻을 게 없고 훼손 위험만 있다. 이 판정을 호출부가 아니라
    # 여기 두는 이유: agent_graph의 후속질문 rewrite 노드도 같은 함수를 쓰는데, 호출부에만
    # 두었더니 그 경로에서 통째로 우회됐다(실측: 'F스포렉스' → 'F스포렉스 기간' → 검색 0건).
    if not force and _is_keyword_query(question):
        print(f"[RAG_GENERAL] 이미 검색어 형태 → 재작성 생략: '{question}'")
        return question

    if prev_question:
        prompt = QUERY_REWRITE_WITH_CONTEXT_PROMPT.format(
            prev_question=prev_question, question=question
        )
    else:
        prompt = QUERY_REWRITE_PROMPT.format(question=question)
    rewritten = await llm_service.answer(
        prompt,
        max_tokens=64,
        system_prompt=KEYWORD_EXTRACTION_SYSTEM_PROMPT,
        temperature=0.0,   # 결정론적 출력으로 창의적 변형(환각) 억제
    )
    rewritten = _clean_rewrite_output(rewritten)   # 빈출력·프롬프트 형식 에코 안전 정리
    # 빈 출력이거나 원본과 동일 → 원본 사용
    if not rewritten or rewritten == question:
        print(f"[RAG_GENERAL] 질문 재작성 실패/빈출력 → 원본 사용: '{question}'")
        return question
    # 주제어 가드: 현재 질문에 뚜렷한 주제어가 있는데 재작성이 그걸 잃었으면(= 이전 주제로
    # 갈아탄 것) 원본 사용. 아래 드리프트 가드는 기준문에 이전 질문이 섞여 있어 이 경우를
    # 못 잡으므로, 그보다 먼저 확정적으로 차단한다.
    if not _keeps_topic(question, rewritten):
        print(f"[RAG_GENERAL] 재작성이 주제어 이탈 → 원본 사용: '{question}' → '{rewritten}' (폐기)")
        return question

    # 행위 개념 날조 가드: 원문·이전질문에 없던 '신청/방법/절차/발급'을 재작성이 만들어 냈으면
    # 폐기한다. 이 프레임이 붙으면 근거에 없는 절차·기한을 LLM이 발명한다(F스포렉스 사례).
    invented = _invents_action(question, rewritten, prev_question)
    if invented:
        print(f"[RAG_GENERAL] 재작성이 없던 '{invented}' 개념 날조 → 원본 사용: '{question}' → '{rewritten}' (폐기)")
        return question

    # 이전 주제 차용 가드: 현재 질문이 스스로 주제를 특정하는데(주제어 보유) 이전 질문의
    # 주제어까지 새로 붙었으면 폐기한다. '학칙 알려줘'(이전 '공결') → '공결 학칙' 오염 차단.
    borrowed = _borrows_prev_topic(question, rewritten, prev_question)
    if borrowed:
        print(f"[RAG_GENERAL] 재작성이 이전 주제어 '{borrowed}' 차용 → 원본 사용: '{question}' → '{rewritten}' (폐기)")
        return question

    # 드리프트 가드: 재작성이 원문과 의미가 너무 멀어지면(예: 공결→전과) 원본 사용
    # 맥락 통합 시엔 주제어가 이전 질문에서 오므로 이전+현재를 합친 텍스트와 비교
    drift_ref = f"{prev_question} {question}" if prev_question else question
    if await _is_semantic_drift(drift_ref, rewritten):
        print(f"[RAG_GENERAL] 재작성 드리프트 감지 → 원본 사용: '{question}' → '{rewritten}' (폐기)")
        return question
    print(f"[RAG_GENERAL] 질문 재작성: '{question}' → '{rewritten}'"
          + (f" (이전 질문 맥락 통합: '{prev_question}')" if prev_question else ""))
    return rewritten


def _search_rag(search_query: str, original_question: str, topic: str | None) -> tuple[str, dict]:
    """Qdrant 검색. topic이 None이면 전체 검색."""
    try:
        print(
            f"[RAG_GENERAL] 선택된 topic: "
            f"{topic if topic else '전체 검색(None)'}"
        )

        context, results = rag_service.search_context_with_results(
            question=search_query,
            topic=topic,
            original_question=original_question,
        )

        metadata = rag_service.primary_metadata(
            results,
            topic=topic,
        )

        print(f"[RAG] context length = {len(context)} chars")
        print(f"[RAG] retrieved chunks = {len(results)}")

        for i, result in enumerate(results, start=1):
            print(
                f"[Chunk {i}] "
                f"score={result.score:.3f}, "
                f"length={len(result.text)}"
            )

        print("\n========== RAG CONTEXT ==========")
        print(context)
        print("=================================\n")

        if context:
            return context, metadata

    except Exception as e:
        print(f"[RAG_GENERAL] 검색 실패: {e}")

    return "", {
        "source": None,
        "source_file": None,
        "topic": topic,
    }


async def answer_rag_general_question_with_metadata(
    question: str,
    topic: str | None = None,
    context_question: str | None = None,
    prev_question: str | None = None,
    search_query: str | None = None,
    db=None,
) -> tuple[str, dict]:
    """RAG 검색 후 LLM 답변 생성.

    topic: agent_graph에서 DB 라우팅으로 결정된 topic_name.
           None이면 전체 검색 (TopicRouter 미분류 — 분류 문장 보강 필요).
    prev_question: topic이 유지된 후속 질문일 때만 전달 — rewrite에 맥락 통합.
    db: 있으면 학사일정 보강에 사용(AsyncSession). 없으면 보강을 건너뛴다.
    """
    print("[RAG_GENERAL] RAG 검색 시작")

    effective_topic = topic
    if effective_topic is None:
        print("[RAG_GENERAL] ⚠️  TopicRouter 분류 실패 — topic=None, 전체 검색. 해당 질문의 분류 문장을 추가하세요.")
        print(f"[RAG_GENERAL] ⚠️  미분류 질문: {question}")

    # search_query가 주어지면(agent_graph의 rewrite 노드가 후속질문을 이미 재작성) 재사용,
    # 없으면(1차 질문) 여기서 구어체→키워드 재작성. (이중 rewrite / 이중 LLM 호출 방지)
    hoisted = search_query is not None
    # 재작성 생략 판정은 _rewrite_query 안에서 이뤄진다. 여기서 같은 판정을 한 번 더 해 두는 건
    # hoisted 경로(agent_graph가 이미 재작성)도 '지연 재작성' 대상에 포함시키기 위해서다.
    skipped_rewrite = _is_keyword_query(question)
    if not hoisted:
        try:
            search_query = await _rewrite_query(question, prev_question=prev_question)
        except Exception as e:
            print(f"[RAG_GENERAL] rewrite 실패(원본 사용): {e}")
            search_query = question

    # 리랭킹 질문: 후속질문 원본은 맥락 없는 파편("기간은?")이라 리랭커 점수가 폭락한다.
    # → 후속(hoisted)은 재작성 쿼리("휴학 기간")로 리랭킹하고, 1차 질문은 기존대로 구어체 원본으로.
    rerank_question = search_query if hoisted else question

    # 파인튜닝 로그는 '확장 전' 재작성 결과를 남긴다 — 딕셔너리 확장은 검색용 보조일 뿐이라
    # 재작성 품질 라벨에 섞이면 안 된다.
    rewritten_for_log = search_query

    # 검색어 딕셔너리 확장 — 임베딩 검색과 리랭킹 양쪽에 적용한다.
    # (문서명이 '학생규칙'인데 질문이 '학칙'인 것처럼 표기가 다른 경우를 잡기 위함.
    #  답변 생성 프롬프트에는 원 질문이 들어가므로 사용자가 보는 내용은 바뀌지 않는다)
    search_query = expand_search_query(search_query)
    rerank_question = expand_search_query(rerank_question)

    loop = asyncio.get_event_loop()
    context, metadata = await loop.run_in_executor(
        None,
        _search_rag,
        search_query,
        rerank_question,
        effective_topic,
    )

    # ── 통합 폴백: 0건이면 '쓰지 않았던 다른 질의'로 한 번 더 ────────────
    # 재작성은 좋을 수도 나쁠 수도 있어서 미리 추측하지 않고 결과로 판정한다.
    #   재작성으로 시작했는데 0건  → 원문으로 (재작성이 질문을 망친 경우)
    #   원문으로 시작했는데 0건    → 그때 재작성 (진짜 용어 매핑이 필요했던 경우, '지연 재작성')
    # 이 두 번째 갈래가 _is_keyword_query의 안전장치다 — 재작성을 생략했다가 정말 필요했던
    # 질문도 구제된다. 실패했을 때만 비용이 들어 정상 경로는 그대로다.
    if not context:
        alt: str | None = None
        if skipped_rewrite:
            try:
                # force=True — 생략 판정을 우회해야 실제로 재작성이 일어난다
                cand = await _rewrite_query(question, prev_question=prev_question, force=True)
                alt = cand if cand and cand != question else None
                if alt:
                    print(f"[RAG_GENERAL] 원문 검색 0건 → 지연 재작성으로 재시도: '{alt}'")
            except Exception as e:
                print(f"[RAG_GENERAL] 지연 재작성 실패(무시): {e}")
        elif rewritten_for_log and rewritten_for_log != question:
            alt = question
            print(f"[RAG_GENERAL] 재작성 검색 0건 → 원문으로 재시도: '{rewritten_for_log}' ↛ '{question}'")

        if alt:
            context, metadata = await loop.run_in_executor(
                None,
                _search_rag,
                expand_search_query(alt),   # 딕셔너리는 점수 검증된 매핑뿐이라 어느 쪽에도 안전
                alt,
                effective_topic,
            )
            if context:
                print("[RAG_GENERAL] ✅ 재시도 성공")
                metadata["query_fallback"] = True
                rewritten_for_log = alt if skipped_rewrite else rewritten_for_log

    # 파인튜닝 데이터용: 실제로 재작성된 경우에만 기록 (원본과 같으면 no-op이므로 None)
    metadata["rewritten_query"] = rewritten_for_log if rewritten_for_log != question else None

    # ── 학사일정 보강 ────────────────────────────────────────────────
    # 절차·서류는 RAG 문서에, 실제 날짜는 academic_schedule 테이블에만 있다. 토픽 라우팅은
    # 배타적 선택이라 leave로 가면 날짜가, schedule로 가면 절차 설명이 통째로 빠진다.
    # → 날짜를 묻는 질문이면 라우팅 결과와 무관하게 해당 일정을 컨텍스트에 얹어 준다.
    #   (DB 조회 1회. LLM·임베딩 호출 없음)
    #
    # 판단에는 원 질문과 재작성 쿼리를 합쳐 쓴다: "언제까지 제출해야해?"는 원문에 이벤트어가
    # 없고, 재작성("휴학 서류 제출 기한")에는 날짜어가 빠질 수 있어 한쪽만 보면 놓친다.
    if db is not None:
        sched_q = f"{question} {rewritten_for_log}" if rewritten_for_log else question
        try:
            from app.services.school.schedule import schedule_service
            sched_rows = await schedule_service.collect_related(sched_q, db)
            if sched_rows:
                # 헤드라인을 질문의 구체 키워드에 맞춰 고르도록 함께 넘긴다
                sched_kws = schedule_service._extract_keywords(sched_q)
                block = schedule_service.build_context_block(sched_rows, sched_kws)
                # 보강 블록은 리트리버가 이미 예산(MAX_TOTAL_CONTEXT)에 맞춰 자른 컨텍스트 '위에'
                # 얹힌다. 예산 밖에서 그냥 더했더니 프롬프트가 n_ctx를 넘어 요청이 통째로
                # 실패했다(ValueError: Requested tokens 4120 exceed context window 4096).
                # → 블록 자리만큼 RAG 컨텍스트를 줄여 총량을 예산 안에 유지한다.
                room = MAX_TOTAL_CONTEXT - len(block)
                if context and len(context) > room:
                    cut = context[:max(0, room)]
                    context = cut.rsplit("\n", 1)[0] if "\n" in cut else cut
                    print(f"[RAG_GENERAL] 학사일정 보강 자리 확보 → RAG 컨텍스트 {len(context)}자로 절단")
                context = (context or "") + block
                metadata["schedule_card"] = schedule_service.build_card(sched_rows)
                print(f"[RAG_GENERAL] 학사일정 보강 {len(sched_rows)}건 추가")
        except Exception as e:
            print(f"[RAG_GENERAL] 학사일정 보강 실패(무시): {e}")

    # 검색 결과가 없으면 LLM 호출 스킵 — 근거 없는 답변(환각) 생성 방지.
    # 다만 그냥 끝내지 않고 다운로드 파일을 먼저 확인한다: 신청 매뉴얼처럼 화면 캡처
    # 위주라 텍스트로 옮기면 뜻이 깨지는 자료는 일부러 Qdrant에 넣지 않는데, 그러면
    # 검색은 항상 0건이라 예전엔 파일이 있어도 "자료 없음"으로 끝나버렸다.
    # 파일 목록은 document_file 테이블(AVAILABLE_FILES)에서 오므로 RAG 색인과 무관하다.
    if not context:
        from pathlib import Path
        from app.services.file_service import AVAILABLE_FILES
        from app.utils.file_matcher import match_relevant_files

        fallback_files = await loop.run_in_executor(
            None, match_relevant_files, question, AVAILABLE_FILES.get(effective_topic, [])
        )
        if fallback_files:
            print(f"[RAG_GENERAL] ⚠️ 검색 결과 0건 → 관련 파일 {len(fallback_files)}개로 안내")
            stems = [Path(f).stem for f in fallback_files]
            metadata["files_to_offer"] = stems
            # 파일명을 답변에 적어준다: '예/아니요' 단계에선 화면에 파일명이 안 보이고
            # (파일 선택 버튼은 '예'를 누른 다음에야 뜬다) 뭘 받는지 모르고 눌러야 하기 때문.
            file_lines = "\n".join(f"- {s}" for s in stems)
            return (
                "질문하신 내용은 챗봇이 글로 정리해 둔 자료에는 없지만, 관련 안내 파일이 준비되어 있어요.\n\n"
                "요약본이 아니라 원본 자료라서 내용이 빠짐없이 담겨 있어요. "
                "파일을 직접 확인하시는 것이 가장 정확합니다.\n\n"
                f"{file_lines}\n\n"
                "파일 드릴까요? 아래 '예'를 누르시면 바로 받으실 수 있어요.",
                metadata,
            )

        print("[RAG_GENERAL] ⚠️ 검색 결과 0건 → LLM 호출 스킵, 안내 응답 반환")
        return (
            "죄송해요, 해당 내용에 대한 자료를 찾지 못했어요. "
            "조금 더 구체적으로 질문해 주시거나, "
            "학교 공식 홈페이지(wsu.ac.kr) 또는 담당 부서에 문의해 주세요.",
            metadata,
        )

    # LLM에는 이전 대화 맥락(이전 주제 힌트)이 포함된 질문 전달
    llm_question = context_question if context_question is not None else question

    print("[RAG_GENERAL] RAG 검색 완료, LLM 호출")

    # 클럽 판정은 "현재 질문" 기준 — llm_question은 이전 주제 프리픽스를 포함하므로
    # 이전 질문에 "동아리"가 있었다고 현재 질문이 클럽 질문이 되는 오탐을 방지한다.
    is_club = "동아리" in question and effective_topic == "student_support"
    _LIST_KEYWORDS = {"목록", "종류", "어떤", "뭐가", "뭐뭐", "다 알", "전부", "모두", "있어", "있나", "있어요", "있나요"}
    is_club_list = is_club and any(kw in question for kw in _LIST_KEYWORDS)
    print(f"[RAG_GENERAL] is_club={is_club}, is_club_list={is_club_list}, topic={effective_topic}")

    from pathlib import Path
    matched_files: list[str] = []   # 임베딩 필터가 고른 관련 파일 (제안 확정용)

    # 프롬프트가 n_ctx를 넘으면 llm_service가 ValueError를 던진다. 여기서 받지 않으면
    # 요청이 500으로 죽어 사용자에게 에러 화면이 나간다 → 안내 문구로 대신한다.
    # (예산 조정으로 거의 안 생겨야 하지만, 마지막 방어선이다)
    try:
        if is_club_list:
            # 동아리 목록은 정형 문서라 코드로 직접 포맷한다(항상 같은 형식). 파싱 실패 시에만
            # LLM 폴백. fit_context는 코드 포맷이 컨텍스트 전체를 쓰므로 폴백일 때만 적용한다.
            answer = format_club_list(context)
            if not answer:
                context = llm_service.fit_context(context, RAG_CLUB_LIST_PROMPT.format(context="") + SYSTEM_PROMPT)
                prompt = RAG_CLUB_LIST_PROMPT.format(context=context)
                answer = await llm_service.answer(prompt, max_tokens=2048, temperature=0.0)
        elif is_club:
            context = llm_service.fit_context(
                context, RAG_CLUB_DETAIL_PROMPT.format(context="", question=llm_question) + SYSTEM_PROMPT)
            prompt = RAG_CLUB_DETAIL_PROMPT.format(context=context, question=llm_question)
            answer = await llm_service.answer(prompt, max_tokens=1024, temperature=0.0)
        else:
            # 파일 제안은 '답변'을 기준으로 뒤에서 판정한다(아래 참조). 프롬프트에서 파일 목록·
            # <FILES> 태그 지시를 뺐다 — 태그는 어차피 화면에서 제거하고 임베딩 결과로 확정하므로
            # 무용했고, 목록을 넣지 않으니 프롬프트가 가벼워진다(오버헤드 감소 → 답변 토큰 여유 증가).
            # 답변 최소 800토큰을 남기도록 컨텍스트를 동적 절단한다. 고정 상수(MAX_TOTAL_CONTEXT)
            # 로는 RAG 골격을 반영 못 해 답변이 61토큰까지 쪼그라들었다(실측). 학사일정 보강 블록도
            # 오버헤드에 포함되므로, 컨텍스트를 뺀 최종 프롬프트로 잰다.
            overhead = RAG_GENERAL_PROMPT.format(context="", question=llm_question) + SYSTEM_PROMPT
            context = llm_service.fit_context(context, overhead)
            prompt = RAG_GENERAL_PROMPT.format(context=context, question=llm_question)
            answer = await llm_service.answer(prompt, max_tokens=1536)
    except ValueError as e:
        print(f"[RAG_GENERAL] ⚠️ 컨텍스트 초과로 생성 불가: {e}")
        return (
            "죄송해요, 관련 자료가 너무 많아 한 번에 정리하지 못했어요. "
            "조금 더 구체적으로(예: 휴학 구분, 학기 등) 질문해 주시면 정확히 안내해 드릴게요.",
            metadata,
        )

    # 모델이 프롬프트 레이블을 이어서 출력하는 경우 가장 앞에 나온 위치에서 잘라내기
    _STOP_MARKERS = ["[참고 문서]", "[사용자 질문]", "[답변]", "[이전 질문]", "[이전 답변]", "[다운로드 가능 파일 목록]"]
    earliest_pos = len(answer)
    earliest_marker = None
    for marker in _STOP_MARKERS:
        pos = answer.find(marker)
        if pos != -1 and pos < earliest_pos:
            earliest_pos = pos
            earliest_marker = marker
    if earliest_marker:
        answer = answer[:earliest_pos].strip()
        print(f"[RAG_GENERAL] 프롬프트 누출 감지 → '{earliest_marker}' 앞에서 잘라냄")

    # 파일 제안은 임베딩 필터(match_relevant_files) 결과로 확정한다.
    # 작은 로컬 LLM이 <FILES> 태그를 불안정하게 누락해 관련 파일을 못 주던 문제 →
    # 이미 검증된 임베딩 유사도 판단을 신뢰하고, LLM이 뽑은 태그는 화면에서 제거만 한다.
    # (잘린 열린 태그 + 표 구분선 '|--|' 누출까지 정리 — clean_answer)
    from app.utils.file_matcher import clean_answer, match_relevant_files
    answer = clean_answer(answer)

    # 파일 매칭은 '완성된 답변' 기준으로 여기서 한다. 질문 기준일 때는 신호가 약해
    # '기숙사 비용 얼마야?'에도 외부인 사용 동의서가 딸려 나왔다(질문 0.559 — 진짜 요청과
    # 구간이 겹쳐 가를 수 없었다). 답변은 '휴학신청서를 제출해야 합니다'처럼 서류 요구가
    # 문장으로 드러나 0.60 기준으로 깨끗하게 갈린다.
    if not matched_files:
        from app.services.file_service import AVAILABLE_FILES
        matched_files = await loop.run_in_executor(
            None, match_relevant_files, answer, AVAILABLE_FILES.get(effective_topic, [])
        )
    if matched_files:
        metadata["files_to_offer"] = [Path(f).stem for f in matched_files]

    return answer, metadata


async def answer_rag_general_question(question: str, topic: str | None = None) -> str:
    answer, _ = await answer_rag_general_question_with_metadata(question, topic=topic)
    return answer
