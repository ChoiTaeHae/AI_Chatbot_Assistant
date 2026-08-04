import asyncio
import math
import re

from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.rag.Retrieval.retriever import MAX_TOTAL_CONTEXT   # 보강 블록도 같은 예산 안에서 다룬다
from app.prompts import RAG_GENERAL_PROMPT, RAG_CLUB_LIST_PROMPT, RAG_CLUB_DETAIL_PROMPT, QUERY_REWRITE_PROMPT, QUERY_REWRITE_WITH_CONTEXT_PROMPT, KEYWORD_EXTRACTION_SYSTEM_PROMPT, SYSTEM_PROMPT, WEAK_EVIDENCE_DIRECTIVE

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
    # 시각을 묻는 말 — '언제'는 있는데 '몇시'가 없어서 주제어로 잡혔다. 실측: '거기 몇시까지해?'의
    # 주제어가 ['몇시까지']가 되는 바람에 _keeps_topic이 정확한 재작성('동캠 학식 운영 시간')을
    # '주제어 이탈'로 폐기했고, 구어체 원본이 그대로 라우팅돼 general(잡담)로 샜다.
    # 접두 일치라 몇시/몇시까지/몇시부터를 모두 덮는다. 실제 질문 2874건 중 3건만 영향을 받고,
    # 그중 주제어가 통째로 비는 건 이 케이스 하나뿐이다('주차 몇시까지 돼?'는 ['주차']로 남음).
    "몇시",
    # 날짜 지시어 — '어느 날'을 가리키는 한정어지 주제가 아니다('몇시'와 같은 층위).
    # 실측: '오늘 학식 뭐야' → '내일은?'의 주제어가 ['내일']로 잡혀, 정확한 재작성
    # ('내일 학식 메뉴')이 _borrows_prev_topic에 '학식 차용'으로 걸려 폐기됐다. 그러면
    # 구어체 원본이 그대로 라우팅돼 general(잡담)로 샌다. 날짜는 학식·학사일정 핸들러가
    # 원문에서 따로 파싱하므로(_resolve_date_key) 주제어에서 빠져도 정보가 사라지지 않는다.
    # 실제 질문 3,146건 중 32건(1.0%)만 이 단어를 포함하고, 그중 날짜어가 유일한 주제어라
    # 판정이 바뀌는 건 '내일은?' 뿐이다('오늘 학식 뭐나와'는 ['학식']으로 남음).
    "오늘", "내일", "모레",
    # 지시대명사 — 이전 주제를 가리키는 말이라 주제어가 아니다("그건 얼마야?")
    "그건", "그거", "그것", "이건", "이거", "이것", "저건", "저거", "저것",
    "거기", "여기", "그때", "그럼", "그러면",
    # 수정 요청·조사 — 주제가 아니라 '다시 해줘' 류의 요청/연결어라 주제어가 아니다.
    # ('2025학번으로 다시 부탁해' 같은 순수 수정요청이 주제어를 가진 새 질문으로 오인되면
    #  이전 주제(간호학과)를 못 붙여 가드가 정답 재작성을 폐기했다. 실측)
    "다시", "부탁", "으로",
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
    # 조건 연결어미 — '받으면·놓치면·탈락하면'처럼 조건절 동사가 주제어로 오인되면
    # 정상적인 맥락 병합이 폐기된다(실측: '학사경고가 뭐야?' 뒤 '두 번 받으면 어떻게 돼?'의
    # 주제어가 ['받으면']으로 잡혀 재작성 '학사경고 누적 제적 기준'이 이탈로 반려 → 검색 0건).
    # 긴 것부터 매칭돼야 하므로 순서 주의. 어간이 2자 미만이면 위 로직이 통째로 버린다.
    "으려면", "하려면", "려면", "으면", "하면", "면",
)
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]+")

# 입학년도·학년 한정어('2025학번', '2025년도', '2학년') — 졸업요건 등의 '속성'이지 주제가 아니다.
# _GENERIC_TERMS는 startswith라 숫자로 시작하는 이 토큰들을 못 걸러 별도 정규식으로 처리한다.
# (졸업 핸들러는 detect_admission_year로 년도를 따로 감지하므로 주제어에서 빠져도 무관)
_YEAR_QUALIFIER_RE = re.compile(r"^\d{1,4}(학번|학년도|년도|학년)")

# 정확 일치로만 거는 속성어 — 단독이면 주제가 아니라 '속성'이지만, _GENERIC_TERMS처럼 startswith로
# 걸면 진짜 주제어를 먹는다('자격'→'자격증', '시간'→'시간표'). exact 일치라 자격증/시간표는 안전.
# ('전과 신청 방법' 뒤 '자격 조건은?'이 '자격'만으로 '검색어 형태'로 오판돼 이전 맥락 병합이
#  통째로 생략되던 문제 — 실측: graduation으로 오라우팅)
# '벌점·기간·비용…'도 같은 층위다 — 단독으로는 무엇의 벌점인지 정해지지 않아 이전 맥락을
# 붙여야 한다. 빠져 있으면 '주제어 보유'로 오판돼 정상적인 맥락 병합이 폐기된다.
# (실측: '기숙사 입사 조건' 뒤 '벌점은 어떻게 되나요?' → 재작성 '기숙사 벌점 기준'이 정확했는데
#  '기숙사 차용'으로 반려 → 원문이 school_rules로 라우팅돼 검색 0건 '못 찾음')
_GENERIC_EXACT = ("자격", "시간", "벌점", "기간", "비용", "요금", "금액",
                  "횟수", "점수", "대상", "서류", "절차", "방법", "조건", "기준")
# 위 속성어에 붙는 조사 — '신청 자격은?'의 '자격은'도 속성어로 인정해 후속 병합이 되게 한다.
# (조사만 떼어 exact 확인하므로 '자격증'·'시간표'는 조사가 아니라 그대로 주제어로 유지된다)
_EXACT_PARTICLES = ("은", "는", "이", "가", "을", "를", "도", "의", "만")


def _distinctive_terms(question: str) -> list[str]:
    """질문에서 '주제를 식별하는' 토큰만 추출 (일반어·서술어 제외).

    비어 있으면 = 주제어 없는 모호한 후속 질문("기간은?") → 이전 맥락 보충이 정상이다.
    (애매하면 비우는 쪽이 안전 — 검사가 skip되어 재작성을 막지 않는다)"""
    terms = []
    for tok in _TOKEN_RE.findall(question or ""):
        if len(tok) < 2:
            continue
        if _YEAR_QUALIFIER_RE.match(tok):     # '2025학번'·'2학년' 등 입학년도/학년 한정어는 주제 아님
            continue
        if any(tok.startswith(g) for g in _GENERIC_TERMS):
            continue
        if tok in _GENERIC_EXACT:             # '자격'·'시간' 등 — 단독이면 속성어(자격증/시간표는 유지)
            continue
        if any(tok.endswith(p) and tok[:-len(p)] in _GENERIC_EXACT for p in _EXACT_PARTICLES):
            continue                          # 조사 붙은 '자격은'·'시간이' 등도 속성어로 처리
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


# 제증명 청크(idx=1)는 '[증명서명]\n내용' 블록으로 재구성돼 있다(2026-07-27, 학점표가
# 엉뚱한 증명서에 붙던 오배치 버그를 데이터 재구성으로 고치면서 도입한 구조).
# [source=..., score=...] 라벨도 '[...]' 형태라 name에서 ','·'=' 문자를 제외해 구분한다.
_CERT_BLOCK_RE = re.compile(r"^\[([^\[\],=]+)\]\s*$", re.MULTILINE)
_CERT_LIST_KEYWORDS = {"종류", "뭐가", "뭐뭐", "다 알", "전부", "모두", "있어", "있나", "있어요", "있나요"}

# search_context_with_results가 여러 청크를 이어붙일 때 청크마다 붙이는 구분선.
# 이 경계에서 먼저 잘라야 한다 — 안 자르면 컨텍스트의 '마지막' 증명서 블록(제적증명서)이
# '다음 [이름] 없으면 끝까지'로 몸통을 잡다가, 뒤에 이어붙은 다른 청크(발급절차·학적부 규정
# 원문 등)까지 통째로 삼킨다(실측: '제증명 종류' 답변에 '[source=...]' 라벨이 그대로 노출됨).
_CHUNK_BOUNDARY_RE = re.compile(r"^\[source=.*?\]\s*$", re.MULTILINE)

# 리트리버가 같은 문서의 청크를 하나로 병합해 넘긴다(retriever.py _merge_same_article, 태해
# 코드). 그래서 idx=1(증명서 블록)과 idx=2/3(발급절차, 대괄호 없는 평문)이 같은 세그먼트로
# 붙어 있을 수 있다 — 마지막 블록(제적증명서)이 '다음 [이름] 없으면 끝까지'로 몸통을 잡다가
# 절차 안내까지 통째로 삼킨다(실측: '제증명 종류' 답변이 발급절차까지 길게 딸려 나옴).
# 대괄호가 없는 절차 헤더라 정규식으로 못 끊으므로, 알려진 헤더 앞에서 잘라낸다.
_CERT_NONBLOCK_HEADERS = ("인터넷 증명서 발급", "국제(해외) 우편 증명서 발급", "상기 콘텐츠")

# '종류' 목록 답변에서 각 증명서를 '한 줄'로 보여줄 때 쓰는 짧은 설명.
# 5종(재학·성적·교육비·휴학·제적)은 원문 자체가 이미 한 줄이라 body를 그대로 쓴다.
# 졸업예정·수료는 원문이 길어(요건 문장·학점표) 목록엔 부적합 → 아래에 사실을 압축한 한 줄을
# 둔다(전체 원문은 특정 증명서를 콕 집어 물으면 matched 분기에서 그대로 나온다).
_CERT_SHORT_DESC = {
    "졸업예정증명서": "졸업 수업연한·요건을 충족한 재학생 또는 졸업종합시험 합격 수료생에게 발급",
    "수료증명서": "학년별 취득학점 기준을 충족한 자에게 발급",
    "재학증명서": "편제학년에 의거 발급",   # 원문("학년별 재학증명서는 ~ 발급한다.")이 완결 문장이라 톤 통일용
}


def _cert_one_line(name: str, body: str) -> str:
    if name in _CERT_SHORT_DESC:
        return _CERT_SHORT_DESC[name]
    return body.splitlines()[0].strip()   # 5종은 이미 한 줄


def _clip_at_nonblock_header(body: str) -> str:
    cut = min((i for h in _CERT_NONBLOCK_HEADERS if (i := body.find(h)) != -1), default=len(body))
    return body[:cut].strip()


def _parse_certificate_blocks(context: str) -> dict[str, str]:
    """context에서 '[증명서명]\n내용' 블록만 추출한다. dict는 삽입 순서를 보존한다."""
    blocks: dict[str, str] = {}
    for segment in _CHUNK_BOUNDARY_RE.split(context):     # 청크 경계 밖으로 못 넘어가게 먼저 분리
        marks = list(_CERT_BLOCK_RE.finditer(segment))
        for i, m in enumerate(marks):
            name = m.group(1).strip()
            start = m.end()
            end = marks[i + 1].start() if i + 1 < len(marks) else len(segment)
            body = _clip_at_nonblock_header(segment[start:end].strip())
            # 이름에 '증명'이 든 블록만 인정 — 딴 문서의 '[공지]' 같은 대괄호 줄을 증명서로
            # 오인하지 않게 한다(토픽 가드를 뗀 뒤의 안전장치). 이 프로젝트 증명서는 모두 '~증명서'.
            if name and body and "증명" in name and name not in blocks:   # 먼저 나온(고득점) 청크 우선
                blocks[name] = body
    return blocks


def format_certificate_info(context: str, question: str) -> str:
    """제증명 종류·발급기준 질문을 코드에서 직접 포맷한다 (club 목록과 동일 원칙).

    LLM에 맡겼을 때 실측된 문제: 수료증명서 학점표가 졸업예정증명서 아래에 잘못 붙거나,
    여러 연도 기준 중 엉뚱한 걸 현행처럼 골랐다(2026-07-27). 블록이 이미 증명서명으로
    깔끔히 나뉘어 있어 LLM이 다시 정리할 이유가 없다 — 코드가 블록을 그대로 옮기면
    오배치 자체가 불가능해진다.
    - 특정 증명서명이 질문에 있으면(목록성 어미 없이) → 그 블록 전체
    - '종류/뭐가 있어' 류면 → 7종을 '이름: 한 줄 설명'으로 세로 정렬(세부는 특정 질문 때)
    - 둘 다 아니면(발급 방법·비용 등 이 블록의 소관이 아닌 질문) → 빈 문자열, LLM에 맡긴다.
    파싱 결과가 없으면(이 청크가 검색에 안 잡힌 경우 등)도 빈 문자열 → 호출부가 LLM 폴백.
    """
    blocks = _parse_certificate_blocks(context)
    if not blocks:
        return ""

    qn = question.replace(" ", "")
    is_list_query = any(kw in question for kw in _CERT_LIST_KEYWORDS)
    matched = [name for name in blocks if name.replace(" ", "") in qn]

    # '떼는 법·발급 방법·어떻게·신청 절차' 같은 절차 질문은 이 블록(증명서 정의·발급기준)의
    # 소관이 아니다. 실제 발급방법(제10조: 신청원 작성→수수료 납부→교무처 제출)은 특정 증명서
    # 블록 밖에 있어, 증명서명만 보고 블록을 반환하면 '편제학년에 의거 발급' 같은 엉뚱한 한 줄만
    # 나온다(실측: '재학증명서 떼는 법'). 이런 질문은 빈 문자열 → LLM이 전체 컨텍스트로 답한다.
    # ('발급 기준'은 블록이 곧 답이므로 '기준'은 절차 신호에서 제외한다)
    #
    # 힌트가 '발급받'이라 뒤에 '받'이 붙어야만 걸렸고, 맨 '발급'을 놓쳤다 — 실측: '성적증명서
    # 발급'이 절차 대신 "[성적증명서] 본 대학에서 이수한 성적의 증명서" 한 줄만 냈다(같은 질문에
    # '방법'만 붙이면 webminwon 절차를 정상 출력). 동어반복이라 정보량이 0인데 답한 것처럼 보인다.
    # 판정이 틀렸을 때의 손해가 대칭이 아니라 넓히는 쪽을 택했다 — 블록을 반환하면 LLM은 그
    # 블록만 보므로 절차를 말할 길이 사라지지만(회복 불가), 스킵하면 전체 컨텍스트를 보므로
    # 기준도 함께 답할 수 있다(회복 가능).
    # 단 '발급 기준/대상/요건/조건/자격'은 블록이 곧 답이므로 그 결합형만 도려내고 검사한다.
    # (문자열을 지우는 방식이라 '발급대상이랑 신청방법'처럼 섞인 질문은 '신청/방법'이 살아남는다)
    _METHOD_HINTS = ("떼", "방법", "어떻게", "어케", "하려면", "려면", "받으러", "받는법", "발급", "신청", "절차")
    _CRITERIA_NOUNS = ("기준", "대상", "요건", "조건", "자격")
    qn_hint = qn
    for _w in _CRITERIA_NOUNS:
        qn_hint = qn_hint.replace("발급" + _w, "")
    is_method_query = any(h in qn_hint for h in _METHOD_HINTS)

    if matched and not is_list_query and not is_method_query:
        return "\n\n".join(f"[{name}]\n{blocks[name]}" for name in matched)
    if is_list_query:
        # '종류가 뭐야' 류엔 각 증명서를 '이름: 한 줄 설명'으로 세로 정렬해 가볍게 보여준다
        # (2026-07-27 실사용 피드백: 상세부터 들이밀면 무겁다). 세부 기준(수료 학점표 등)은
        # 특정 증명서를 콕 집어 물으면 위 matched 분기에서 전체가 나온다.
        lines = "\n".join(f"- {name}: {_cert_one_line(name, body)}" for name, body in blocks.items())
        return f"제증명은 총 {len(blocks)}종입니다.\n\n{lines}"
    return ""


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
    # '떼는 법/떼려면/떼고 싶어/떼주세요'='발급 방법' — 증명서 '떼다'류 구어를 방법 씨앗으로 인정.
    # '는법/려면'은 일반형(가는 법, 하려면 등)까지, '떼고/떼주'는 떼 동사에 붙은 형태만(먹고 싶어·
    # 알려주세요 같은 비-떼 질문엔 영향 없음).
    "방법": ("방법", "어떻게", "어케", "하는법", "는법", "하려면", "려면", "떼고", "떼주", "어디"),
    "신청": ("신청", "접수", "지원", "넣", "내려"),
    "절차": ("절차", "과정", "순서", "어떻게", "하려면", "어디"),
    # '발급'만 방법 씨앗이 빠져 있어, 증명서류 질문에서 '어떻게 해?'가 '발급 방법'으로 정규화되는
    # 정당한 변환이 날조로 오판됐다(실측: '재증명 어떻게해?' → '제증명 발급 방법' 폐기 → 구어 원본이
    # 그대로 라우팅돼 '재-'가 재입학과 가까워 readmission으로 새고 검색 0건).
    # '뭐야/얼마야'는 여전히 넣지 않으므로 '○○이 뭐야?' → '○○ 발급 방법' 같은 성격 변질은 계속 막힌다.
    "발급": ("발급", "떼", "받", "어떻게", "어케", "하려면", "려면", "방법", "하는법", "는법"),
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
    if any(_stem_in(t, rw) for t in terms):
        return True

    # 표기만 바뀐 경우(오타 교정·동의어)는 '이탈'이 아니다. 양쪽을 검색어 딕셔너리의
    # 공식어로 환산해 겹치면 같은 주제로 본다.
    # 실측: '재증명 어떻게해?'(오타) → '제증명 발급 방법'(정확한 교정)이 글자가 달라
    # 폐기됐고, 구어 원본이 그대로 라우팅돼 '재-'가 재입학과 가까워 readmission으로 샜다
    # (0.663 → 검색 0건). 둘 다 '증명서'로 환산되므로 여기서 살린다.
    q_off = _official_terms(question)
    if q_off and (q_off & _official_terms(rewritten)):
        return True
    return False


# ── 검색어 딕셔너리 ────────────────────────────────────────────────
# 학생이 쓰는 말 → 문서에 실제 존재하는 공식 용어.
# 문서에 없는 용어를 덧붙이면 오히려 검색이 망가지므로(실측: '간사 뽑는거 언제야'에
# '조교 모집'을 더하자 0.336 → 0.000) 점수로 검증된 매핑만 등록한다.
# DB(app_config, key="search_synonyms")에서 로드하며 아래는 시딩용 기본값.
DEFAULT_SEARCH_SYNONYMS: dict[str, list[str]] = {
    "학칙": ["학생규칙"],     # 실측 0.014 → 0.642
    "공결": ["출석인정"],     # 실측 0.051 → 0.994
    "제증명": ["증명서"],     # 리랭커가 합성어 '제증명'을 문서의 '증명서'와 매칭 못함.
                              # 회귀 harness: '제증명 뭐 뗄 수 있어' 0건 → PASS (문서에 있는 공식어라 안전)
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


def _official_terms(text: str) -> set[str]:
    """텍스트에 들어 있는 딕셔너리 표제어를 '공식어 집합'으로 환산.

    '재증명'과 '제증명'처럼 표기가 달라도 같은 공식어('증명서')로 모이면 같은 주제로
    볼 수 있다. _keeps_topic이 오타 교정을 주제 이탈로 오판하지 않도록 쓰는 보조 함수.
    """
    t = (text or "").replace(" ", "")
    out: set[str] = set()
    for term, officials in _search_synonyms.items():
        if term.replace(" ", "") in t:
            out.update(o.replace(" ", "") for o in officials)
    return out


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


def expand_document_title(title: str) -> str:
    """문서(파일) 제목에 공식 용어가 있으면 학생이 쓰는 구어 용어를 덧붙인다 — 위 함수의 역방향.

    파일 제안이 임베딩 유사도로 걸러지는데(file_matcher), 질문·답변은 '공결'이라 부르는 반면
    파일명은 '출석인정 요청서 및 결석 사유별 내역서(양식)'이라 유사도가 0.587까지밖에 안 붙어
    기준(0.60)에서 컷됐다(실측). 같은 사전을 반대로 써서 제목 쪽에 '공결'을 붙이면 0.693으로
    올라 통과한다. 사전에는 문서에 실재하는 용어만 등록돼 있어 없는 말을 지어내지 않고,
    사전 단어가 없는 제목은 그대로 반환하므로 대부분의 파일에는 아무 영향이 없다.
    """
    if not title:
        return title
    tn = title.replace(" ", "")
    additions: list[str] = []
    for term, officials in _search_synonyms.items():
        if term.replace(" ", "") in tn:
            continue                       # 구어 용어가 이미 제목에 있음
        if any(o.replace(" ", "") in tn for o in officials) and term not in additions:
            additions.append(term)
    if not additions:
        return title
    return f"{' '.join(additions)} {title}"


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


async def _respace_query(q: str) -> str | None:
    """검색어의 '띄어쓰기만' 교정한다(단어 추가·삭제·변경 금지).

    ko-reranker가 붙여 쓴 한국어 복합어를 무관 문서로 오판하는 문제를 구제하기 위한 것.
    (실측: '주차정기권 요금' → 리랭크 0.14로 정답 문서 탈락 / '주차 정기권 요금' → 0.99로 정답)
    벡터 검색은 붙여써도 정답 문서를 잘 찾으므로 리랭커 필터에서만 걸러지는데, 여기서
    띄어쓰기를 바로잡으면 리랭커가 제대로 점수를 매긴다.

    안전장치: 공백을 제외한 글자열이 원본과 완전히 같을 때만 채택한다. LLM이 단어를
    바꾸거나 지어내면(글자열이 달라지면) 폐기 → 환각·주제이탈 위험 없음. 0건일 때만
    호출되므로 정상 검색 경로의 지연·비용은 0이다."""
    try:
        raw = await llm_service.answer(
            "붙여 쓴 한국어 검색어를 자연스럽게 띄어 써라. 뜻은 그대로 두고 공백만 넣어 한 줄로 출력해라.\n"
            "주차정기권요금 → 주차 정기권 요금\n"
            "수강신청기간 → 수강 신청 기간\n"
            "국가장학금신청방법 → 국가 장학금 신청 방법\n"
            f"{q} →",
            max_tokens=48,
            system_prompt=KEYWORD_EXTRACTION_SYSTEM_PROMPT,
            temperature=0.0,
        )
    except Exception as e:
        print(f"[RAG_GENERAL] 띄어쓰기 교정 실패(무시): {e}")
        return None
    cand = _clean_rewrite_output(raw)
    # 실제로 띄어쓰기가 바뀌었고(=원본과 다름) & 내용은 그대로(공백 제외 동일)일 때만 채택
    if cand and cand != q and cand.replace(" ", "") == q.replace(" ", ""):
        return cand
    return None


# ── 재작성 실패·반려 시 폴백 정규화 ────────────────────────────────
# LLM 재작성이 실패(429·장애)하거나 가드에 반려되면 지금까지는 '구어체 원문'을 그대로 검색에
# 넣었다. 그런데 리랭커는 구어체에 극도로 약해 30개 청크가 전부 0.000이 되는 일이 잦다
# (실측: '내년에 졸업하려면 뭐 필요해?'). 그래서 LLM 없이 군말·어미만 걷어낸 검색어를 만든다.
#
# 원칙: **의미어는 절대 건드리지 않는다.** 요건·기준·조건·학점·방법·절차·신청·기간·자격 등은
# 검색에 꼭 필요한 말이라 제거 대상에 넣지 않는다(학과명 추출용 _DEPT_KW_STOPWORDS를 재사용하면
# 이것들까지 날아가므로 별도 목록을 쓴다).
# 이 결과는 '검색어·라우팅'에만 쓰이고, LLM 답변 프롬프트에는 항상 원문이 들어간다
# (llm_question) — 그래서 질문 의도가 훼손되지 않는다.
_FALLBACK_FILLERS = (
    "알려주세요", "알려줘", "알려", "해주세요", "해줘", "주세요",
    "뭐에요", "뭔가요", "뭐야", "뭔데", "궁금해요", "궁금해", "궁금",
    "어떻게해", "어떻게 해", "어떡해", "좀",
    "인가요", "하나요", "되나요", "있나요", "있어요", "습니까", "까요",
)
_FALLBACK_PARTICLES = ("으로", "에서", "까지", "부터", "은", "는", "이", "가",
                       "을", "를", "도", "의", "에", "과", "와")


def _fallback_normalize(question: str) -> str:
    """군말·어미·조사만 걷어낸 검색용 문자열. 남는 게 없으면 원문을 그대로 돌려준다."""
    if not question:
        return question
    s = question
    for w in _FALLBACK_FILLERS:
        s = s.replace(w, " ")
    s = re.sub(r"[?!.,~·]+", " ", s)
    toks = []
    for t in s.split():
        for p in _FALLBACK_PARTICLES:
            if t.endswith(p) and len(t) - len(p) >= 2:
                t = t[: -len(p)]
                break
        if t:
            toks.append(t)
    out = " ".join(toks).strip()
    if not out or len(out) < 2:
        return question
    if out != question:
        print(f"[RAG_GENERAL] 폴백 정규화: '{question}' → '{out}'")
    return out


async def _rewrite_query(question: str, prev_question: str | None = None, force: bool = False,
                         normalize_on_reject: bool = False) -> str:
    """구어체 질문을 검색용 공식 용어로 변환.

    prev_question이 있으면(topic 유지된 후속 질문) 이전 질문의 주제어를 보충해
    재작성한다 — "기간은 얼마나 돼?"가 엉뚱한 검색어로 변환되는 것을 방지.

    normalize_on_reject=True면 가드 반려·빈출력 시 원문 대신 '규칙 기반 정규화문'을 돌려준다.
    검색 전용 호출에서만 켠다 — 라우팅에 쓰면 군말 제거로 임베딩이 미세하게 움직여 근소한
    차이의 토픽이 뒤집힌다(실측: '국가장학금 소득분위 기준 알려줘' scholarship→work_study).

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
        return _fallback_normalize(question) if normalize_on_reject else question
    # 주제어 가드: 현재 질문에 뚜렷한 주제어가 있는데 재작성이 그걸 잃었으면(= 이전 주제로
    # 갈아탄 것) 원본 사용. 아래 드리프트 가드는 기준문에 이전 질문이 섞여 있어 이 경우를
    # 못 잡으므로, 그보다 먼저 확정적으로 차단한다.
    if not _keeps_topic(question, rewritten):
        print(f"[RAG_GENERAL] 재작성이 주제어 이탈 → 원본 사용: '{question}' → '{rewritten}' (폐기)")
        return _fallback_normalize(question) if normalize_on_reject else question

    # 행위 개념 날조 가드: 원문·이전질문에 없던 '신청/방법/절차/발급'을 재작성이 만들어 냈으면
    # 폐기한다. 이 프레임이 붙으면 근거에 없는 절차·기한을 LLM이 발명한다(F스포렉스 사례).
    invented = _invents_action(question, rewritten, prev_question)
    if invented:
        print(f"[RAG_GENERAL] 재작성이 없던 '{invented}' 개념 날조 → 원본 사용: '{question}' → '{rewritten}' (폐기)")
        return _fallback_normalize(question) if normalize_on_reject else question

    # 이전 주제 차용 가드: 현재 질문이 스스로 주제를 특정하는데(주제어 보유) 이전 질문의
    # 주제어까지 새로 붙었으면 폐기한다. '학칙 알려줘'(이전 '공결') → '공결 학칙' 오염 차단.
    borrowed = _borrows_prev_topic(question, rewritten, prev_question)
    if borrowed:
        print(f"[RAG_GENERAL] 재작성이 이전 주제어 '{borrowed}' 차용 → 원본 사용: '{question}' → '{rewritten}' (폐기)")
        return _fallback_normalize(question) if normalize_on_reject else question

    # 드리프트 가드: 재작성이 원문과 의미가 너무 멀어지면(예: 공결→전과) 원본 사용
    # 맥락 통합 시엔 주제어가 이전 질문에서 오므로 이전+현재를 합친 텍스트와 비교
    drift_ref = f"{prev_question} {question}" if prev_question else question
    if await _is_semantic_drift(drift_ref, rewritten):
        print(f"[RAG_GENERAL] 재작성 드리프트 감지 → 원본 사용: '{question}' → '{rewritten}' (폐기)")
        return _fallback_normalize(question) if normalize_on_reject else question
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
            search_query = await _rewrite_query(question, prev_question=prev_question,
                                               normalize_on_reject=True)
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
                cand = await _rewrite_query(question, prev_question=prev_question, force=True,
                                        normalize_on_reject=True)
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

    # ── 마지막 폴백: 띄어쓰기 교정 재시도 ────────────────────────────
    # 위 재시도까지 0건이면, 붙여 쓴 복합어를 리랭커가 오판했을 수 있다(예: '주차정기권').
    # 검색어의 '띄어쓰기만' 바로잡아 한 번 더 검색한다. 0건일 때만 발동하므로 정상 경로엔
    # 영향이 없고, 내용은 그대로라(공백 제외 동일 검증) 환각·주제이탈 위험도 없다.
    if not context:
        base = rewritten_for_log or question
        respaced = await _respace_query(base)
        if respaced:
            print(f"[RAG_GENERAL] 0건 → 띄어쓰기 교정 재시도: '{base}' → '{respaced}'")
            context, metadata = await loop.run_in_executor(
                None,
                _search_rag,
                expand_search_query(respaced),
                respaced,
                effective_topic,
            )
            if context:
                print("[RAG_GENERAL] ✅ 띄어쓰기 교정 재시도 성공")
                metadata["query_fallback"] = True
                rewritten_for_log = respaced

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

        # 1순위: 큐레이션 FAQ (검수된 정확한 답변이 애매한 파일 제안보다 우선).
        from app.services.faq_index import faq_lookup
        loop = asyncio.get_event_loop()
        hit = await loop.run_in_executor(None, faq_lookup, question)
        if hit:
            print("[RAG_GENERAL] 문서 0건이지만 FAQ 매칭 → verbatim 답변")
            metadata["source"] = "faq"
            for k in ("url", "contact_name", "contact_phone", "source_file"):
                metadata.pop(k, None)
            return hit[0], metadata

        # 2순위: 관련 안내 파일. 단 여기선 '질문' 기준 매칭이라 노이즈가 커, 답변 기준(0.60)보다
        # 엄격한 0.72로 건다 — 토픽 오라우팅으로 딸려온 무관 파일(예: '학생증 재발급'→'재입학_허가_
        # 서류' 0.681) 제안을 막는다. 확실히 관련된 파일(0.72+)만 안내한다.
        fallback_files = await loop.run_in_executor(
            None, match_relevant_files, question, AVAILABLE_FILES.get(effective_topic, []), 0.72
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
    # 제증명 코드 렌더링 게이트: 토픽 분류에 의존하지 않는다(예전 == "rag_general"은 제증명이
    # '미분류'로 떨어질 때만 성립해, 나중에 증명서 토픽을 추가하면 조용히 죽는 시한폭탄이었다).
    # 질문에 증명서 언급이 있으면 시도만 하고, 실제 발동은 format_certificate_info가 컨텍스트에서
    # '[증명서명]' 블록을 파싱했을 때만(블록 없으면 "" 반환 → LLM 폴백). 어느 토픽이든 견고하게 동작.
    is_certificate = any(k in question for k in ("증명서", "제증명"))
    print(f"[RAG_GENERAL] is_club={is_club}, is_club_list={is_club_list}, is_certificate={is_certificate}, topic={effective_topic}")

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
            # 제증명 종류·기준은 club 목록과 동일 원칙으로 코드가 먼저 시도한다(위 함수 설명 참조).
            # 파싱 실패(청크가 검색에 안 잡힘 등)면 빈 문자열 → 아래 기존 LLM 경로로 그대로 이어진다.
            answer = format_certificate_info(context, question) if is_certificate else ""
            if not answer:
                # 파일 제안은 '답변'을 기준으로 뒤에서 판정한다(아래 참조). 프롬프트에서 파일 목록·
                # <FILES> 태그 지시를 뺐다 — 태그는 어차피 화면에서 제거하고 임베딩 결과로 확정하므로
                # 무용했고, 목록을 넣지 않으니 프롬프트가 가벼워진다(오버헤드 감소 → 답변 토큰 여유 증가).
                # 답변 최소 800토큰을 남기도록 컨텍스트를 동적 절단한다. 고정 상수(MAX_TOTAL_CONTEXT)
                # 로는 RAG 골격을 반영 못 해 답변이 61토큰까지 쪼그라들었다(실측). 학사일정 보강 블록도
                # 오버헤드에 포함되므로, 컨텍스트를 뺀 최종 프롬프트로 잰다.
                overhead = RAG_GENERAL_PROMPT.format(context="", question=llm_question) + SYSTEM_PROMPT
                context = llm_service.fit_context(context, overhead)
                prompt = RAG_GENERAL_PROMPT.format(context=context, question=llm_question)
                # 리랭커 0점 → 어휘 매칭으로만 살아난 컨텍스트면 '단정 금지' 지시를 앞에 붙인다.
                if metadata.get("weak_evidence"):
                    print("[RAG_GENERAL] ⚠️ 근거 약함(어휘 매칭 구제) → 단정 금지 지시 주입")
                    prompt = WEAK_EVIDENCE_DIRECTIVE + prompt
                # 사실 조회 답변은 결정론적으로(temp 0.0) — 같은 질문에 목록·표 완비가 매번 달라지던
                # 변덕 억제(예: 주차 정기권 3개 요금 중 1개만 뽑힘). 졸업·일정·동아리 핸들러와 동일 원칙.
                answer = await llm_service.answer(prompt, max_tokens=1536, temperature=0.0)
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

    # RAG가 무관 문서를 confident하게 잡아 LLM이 '못 찾음'으로 답한 경우 → 큐레이션 FAQ를 최후로
    # 조회한다. 0건이 아니라 '문서는 있지만 답이 없음'이라 위쪽 0건-FAQ 폴백에 안 걸린다.
    # (과잠·엠티 등 FAQ감이 RAG 토픽으로 새면서 무관 문서를 잡은 경우를 여기서 건진다. 실측:
    #  '엠티 신청 언제야?'가 cs 게시판 문서를 잡아 '못 찾음' 답 → FAQ 0.742는 조회조차 안 됐다)
    _NOT_FOUND_MARKERS = ("찾지 못", "찾을 수 없", "제공된 문서에", "관련 자료가 없", "관련 자료를 찾")
    if any(mk in answer for mk in _NOT_FOUND_MARKERS):
        from app.services.faq_index import faq_lookup
        hit = await loop.run_in_executor(None, faq_lookup, question)
        if hit:
            print("[RAG_GENERAL] LLM 무응답 + FAQ 매칭 → verbatim 답변")
            metadata["source"] = "faq"
            # 잡았던 무관 문서의 출처·연락처가 FAQ 답변에 붙지 않도록 비운다.
            for k in ("url", "contact_name", "contact_phone", "source_file"):
                metadata.pop(k, None)
            return hit[0], metadata

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
