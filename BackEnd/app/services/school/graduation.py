

import asyncio
import re
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, distinct

from app.models.DB_Table import (
    Student, Department, RequirementSet, RequirementRule,
    StudentAchievement, Course, StudentCourse
)
from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.rag.Embedding import BaaiEmbedding, baai_embedding
from app.prompts import (
    GRADUATION_DB_PROMPT, GRADUATION_RAG_PROMPT, GRADUATION_COMBINED_PROMPT,
    GRADUATION_OTHER_DEPT_PROMPT, GRADUATION_MY_DEPT_PROMPT,
)


# ── 학과명 매칭 (별칭 기반) ─────────────────────────────────────────
# 질문에 다른 학과가 언급됐는지 코드로 판별 (8B 판단에 맡기지 않음).
# 서버/첫 호출 시 DB에서 (id, name, aliases)를 캐시로 로드한다.
_DEPT_CACHE: list[tuple[int, str, list[str]]] | None = None


# 학과명에 쓰이는 가운뎃점 변형들 — 입력기·문서마다 다른 코드포인트가 나온다.
# (DB 학과명은 U+00B7, 규정 문서는 U+2024를 쓰고, 한/글·MS Word 복붙은 U+2027,
#  일본어 IME가 켜져 있으면 U+30FB/U+FF65가 섞인다. 하나라도 빠지면 그 표기로 물었을 때
#  학과 인식이 통째로 실패하므로 비교 단계에서 모두 지운다.)
_SEP_CHARS = "·․‧・･•"          # U+00B7 U+2024 U+2027 U+30FB U+FF65 U+2022
_NORM_RE = re.compile(r"[\s" + _SEP_CHARS + r"/,]")


def _norm(s: str) -> str:
    """비교용 정규화 — 공백·가운뎃점 변형·구분자(/,) 제거 + 소문자."""
    return _NORM_RE.sub("", s or "").lower()


def detect_department(question: str) -> tuple[int, str] | None:
    """질문에서 학과명/별칭을 탐지해 (dept_id, name) 반환. 가장 긴 매칭 우선(부분매칭 오탐 방지).
    캐시 미로드 또는 미매칭이면 None → 호출부에서 '내 학과'로 폴백."""
    if not _DEPT_CACHE:
        return None
    q = _norm(question)
    best: tuple[int, int, str] | None = None   # (매칭길이, id, name)
    for did, name, aliases in _DEPT_CACHE:
        for term in [name, *(aliases or [])]:
            nt = _norm(term)
            if nt and nt in q and (best is None or len(nt) > best[0]):
                best = (len(nt), did, name)
    return (best[1], best[2]) if best else None


# 질문에 명시된 입학연도(학번) 탐지 — 학과와 같은 원리로 '명시되면 그 기준, 없으면 내 학번'.
# 요건은 학과 × 입학연도로 DB에 있으므로(43학과 × 2020~2026), 연도를 못 읽으면 남의 학번을
# 물어도 내 학번 요건이 나온다("2025학년도 컴퓨터공학과 졸업요건"인데 2022 기준 답변).
#   지원 표기: '2025학번', '2025학년도', '25학번', '25학년도 입학'
_YEAR_4_RE = re.compile(r"(20\d{2})\s*(?:학번|학년도)")
_YEAR_2_RE = re.compile(r"(?<!\d)(\d{2})\s*학번")
# 명시적으로 언급된 '졸업 목표 연도'("2029년 졸업", "2029년도 2월 졸업 예정") — 엄밀히는 학번이
# 아니지만 사용자가 그 연도 기준 요건을 물은 것으로 보고 '대상 연도'로 삼는다. 학번/학년도가
# 있으면 그쪽이 우선(자기 코호트를 명시한 것). 등록 안 된 미래 연도면 리졸버가 가장 가까운
# 연도로 폴백하고 그 사실을 답변에 고지한다("2029년 졸업요건은 없어 2026년 기준으로 안내").
_YEAR_GRAD_RE = re.compile(r"(20\d{2})\s*년도?\s*(?:2월\s*)?졸업")


def detect_admission_year(question: str) -> int | None:
    """질문에 명시된 '요건 기준 연도'를 탐지. 없으면 None → 호출부에서 '내 학번'으로 폴백.

    우선순위: 학번/학년도(자기 코호트 명시) > 2자리 학번 > 졸업 목표 연도.
    """
    if not question:
        return None
    m = _YEAR_4_RE.search(question)
    if m:
        return int(m.group(1))
    m = _YEAR_2_RE.search(question)
    if m:
        return 2000 + int(m.group(1))   # '25학번' → 2025
    m = _YEAR_GRAD_RE.search(question)
    if m:
        return int(m.group(1))          # '2029년 졸업' → 2029 (없으면 리졸버가 폴백+고지)
    return None

# ── 졸업 질문 유형 분류 프로토타입 (임베딩 기반) ──────────────────────
# personal : 개인 현황 조회 (DB)
# document : 공식 절차/일정 조회 (RAG)
# both     : 졸업요건 일반 질문 (DB + RAG)
_GRADUATION_PROTOTYPES: dict[str, list[str]] = {
    "personal": [
        "내 졸업학점이 얼마나 남았나요?",
        "제 이수현황을 알고 싶어요",
        "저 졸업 가능한가요?",
        "내가 전공 학점이 몇 점 남았어요?",
        "나는 교양 이수가 충분한가요?",
        "제 졸업요건 충족 여부 알려주세요",
        "저의 졸업 상태를 확인해주세요",
    ],
    "document": [
        "졸업 신청 방법이 어떻게 되나요?",
        "졸업 서류 제출 절차가 어떻게 되나요?",
        "졸업사정 일정이 언제예요?",
        "졸업 신청 기간이 언제인가요?",
        "졸업 신청은 어디서 하나요?",
        "졸업 관련 규정을 알고 싶어요",
        # 편입생·학번별 요건은 '내 현황'(personal/both)이 아니라 '규정 정보' 조회다.
        # both로 가면 _answer_my_dept가 학생 학과 기준으로만 검색해(RAG 쿼리 고정) 편입생·학번
        # 문서를 못 찾고 개인 학점현황만 섞여 나온다. document로 보내 원본 질문으로 RAG 검색시킨다.
        "편입생은 몇 학점을 이수해야 하나요?",
        "편입생 졸업 이수학점 기준이 어떻게 되나요?",
        "2025학번 교양 이수학점 기준을 알려주세요",
        "학번별 졸업 이수학점 기준이 궁금해요",
        "2020학번 교양 몇 학점 들어야 하나요?",
        "몇 학번은 교양 몇 학점 들어야 해요?",
    ],
    "both": [
        "졸업하려면 학점이 몇 점 필요해요?",
        "졸업요건이 어떻게 되나요?",
        "전공필수를 다 들어야 졸업할 수 있나요?",
        "교양필수 학점이 몇 학점이에요?",
        "이수조건을 알고 싶어요",
        "영어 인증이 졸업에 필요한가요?",
        "졸업까지 뭘 더 들어야 하나요?",
    ],
}


# 유형 분류 점수 = 카테고리 프로토타입 중 질문과 가장 가까운 상위 K개의 평균 유사도.
# (평균 프로토타입은 "졸업요건 어떻게 되니?" 같은 혼합 표현을 오분류 → top-K로 완화.
#  topic_router와 동일 원리.)
_GRAD_TOP_K = 3


class _GraduationClassifier:
    """졸업 질문 유형 임베딩 분류기 (personal / document / both)"""

    def __init__(self):
        self._embedding: BaaiEmbedding | None = None
        self._proto_vecs: dict[str, list[list[float]]] | None = None   # 카테고리별 개별 문장 벡터

    @property
    def embedding(self) -> BaaiEmbedding:
        if self._embedding is None:
            self._embedding = baai_embedding   # 전역 싱글턴 공유 (모델 1회 로드)
        return self._embedding

    def _warmup(self) -> None:
        categories = list(_GRADUATION_PROTOTYPES.keys())
        all_sentences: list[str] = []
        ranges: list[tuple[int, int]] = []
        for cat in categories:
            start = len(all_sentences)
            all_sentences.extend(_GRADUATION_PROTOTYPES[cat])
            ranges.append((start, len(all_sentences)))

        all_vecs = self.embedding.embed_texts(all_sentences)
        self._proto_vecs = {}
        for cat, (start, end) in zip(categories, ranges):
            self._proto_vecs[cat] = all_vecs[start:end]   # 개별 문장 벡터 보관 (평균 안 함)
        print(f"[GraduationClassifier] {len(categories)}개 유형 임베딩 완료")

    def classify(self, question: str) -> str:
        if self._proto_vecs is None:
            self._warmup()

        q_vec = self.embedding.embed_text(question)
        best_cat, best_score = "both", -1.0
        for cat, vecs in self._proto_vecs.items():
            # 개별 문장 유사도 중 상위 K개 평균 (평균 프로토타입 대신)
            sims = sorted((sum(x * y for x, y in zip(q_vec, v)) for v in vecs), reverse=True)
            k = min(_GRAD_TOP_K, len(sims))
            score = sum(sims[:k]) / k
            if score > best_score:
                best_score, best_cat = score, cat

        print(f"[GraduationClassifier] 유형 분류 → {best_cat} ({best_score:.3f})")
        return best_cat


_graduation_classifier = _GraduationClassifier()


class GraduationService:

    # =============================================
    # 메인 진입점
    # =============================================

    async def answer_graduation_with_metadata(self, question: str, student_id: int, db: AsyncSession) -> tuple[str, dict]:
        """Agent가 호출하는 메인 함수 — 개인현황/문서/다른학과를 코드로 분기.

        - 질문에 '내 학과가 아닌 다른 학과'가 언급되면 → 그 학과 요건(DB, 내 입학연도 기준)
          + RAG. 본인 이수현황은 절대 섞지 않는다(환각 방지).
        - 그 외: 유형 분류(personal/document/both)로 개인현황(DB)+문서(RAG) 라우팅.
        """
        await self._ensure_dept_cache(db)
        student, my_dept_name = await self._get_student(db, student_id)
        if not student:
            return await self._answer_from_rag(question)
        try:
            my_year = int(student.student_no[:4])
        except (ValueError, TypeError, IndexError):
            my_year = 2026

        mentioned = detect_department(question)
        is_other = bool(mentioned and mentioned[0] != student.dept_id)
        # 질문에 학번이 명시되면 그 연도 요건으로 답한다(요건은 학과×입학연도로 다르다).
        mentioned_year = detect_admission_year(question)
        is_other_year = bool(mentioned_year and mentioned_year != my_year)
        target_year = mentioned_year or my_year
        print(f"[Graduation] 분기 판별: 언급학과={mentioned}, 내학과id={student.dept_id}, 다른학과={is_other}, "
              f"언급학번={mentioned_year}, 내학번={my_year}, 다른학번={is_other_year}")

        # 다른 학과 또는 다른 학번 → 그 기준의 요건만 (개인 이수현황은 '내 학과·내 학번'에서만
        # 의미가 있으므로 제외한다. 2025학번 요건에 2022학번인 내 현황을 섞으면 오해를 부른다)
        if is_other or is_other_year:
            dept_id = mentioned[0] if mentioned else student.dept_id
            dept_name = mentioned[1] if mentioned else my_dept_name
            return await self._answer_dept_requirement(question, dept_id, dept_name, target_year, db)

        # 내 학과(또는 학과 미언급) → 유형 분류로 라우팅
        cat = await self._classify_question(question)
        if cat == "document":
            # 절차/일정 질문 → RAG
            return await self._answer_from_rag(question)
        # personal / both → 내 학과 졸업요건(학점+서술형) + 본인 학점 이수현황을 함께
        # (요건/현황 분류가 표현 겹침으로 불안정 → 둘 다 보여줘 분류 어려움을 우회)
        # target_year는 여기선 항상 my_year와 같다(다르면 위 분기로 빠짐) — 의도를 드러내려 통일.
        return await self._answer_my_dept(question, student.dept_id, my_dept_name, target_year, student_id, db)

    async def _ensure_dept_cache(self, db: AsyncSession) -> None:
        """학과 매칭 캐시 지연 로드 (첫 졸업 질문 시 1회)."""
        global _DEPT_CACHE
        if _DEPT_CACHE is None:
            rows = (await db.execute(
                select(Department.id, Department.name, Department.aliases)
            )).all()
            _DEPT_CACHE = [(r[0], r[1], r[2] or []) for r in rows]
            print(f"[Graduation] 학과 매칭 캐시 {len(_DEPT_CACHE)}개 로드")

    async def _answer_dept_requirement(self, question: str, dept_id: int, dept_name: str,
                                       admission_year: int, db: AsyncSession) -> tuple[str, dict]:
        """학과 졸업요건 답변 (본인/타 학과 공통) — 그 학과 요건 수치(DB) + 서술형 규정(RAG).
        개인 이수현황은 미포함. '요건' 질문(both) 및 '다른 학과' 질문에 사용."""
        from pathlib import Path
        from app.services.file_service import AVAILABLE_FILES
        from app.utils.file_matcher import match_relevant_files, clean_answer

        rule, actual_year, is_fallback = await self._resolve_requirement_rule(db, dept_id, admission_year)
        if rule:
            fallback_note = (
                f"※ 요청하신 {admission_year}년 졸업요건은 등록돼 있지 않습니다. "
                f"가장 가까운 {actual_year}년 졸업요건으로 대신 안내합니다.\n"
            ) if is_fallback else ""
            req_context = (
                fallback_note +
                f"학과: {dept_name} ({actual_year}학번 기준)\n"
                f"전공 최소 이수학점: {rule.min_credits_major}학점\n"
                f"교양 최소 이수학점: {rule.min_credits_liberal}학점\n"
                f"졸업 총 이수학점: {rule.min_credits_total}학점\n"
                f"영어 공인성적: 필요"
            )
        else:
            req_context = f"{dept_name} {admission_year}학번 졸업요건 정보가 DB에 등록되어 있지 않습니다."

        # RAG(서술형 규정) 검색은 회화체·이전맥락이 낀 원 질문 대신 '학과 키워드'로 리랭킹한다.
        # (리랭커는 쿼리 노이즈에 극도로 민감 — "간호학과 졸업요건"=0.77 vs "…알려줘+맥락"=0.13)
        # 쿼리는 '학과명 + 졸업요건'까지만. 일반어를 덧붙이면 리랭커 점수가 무너진다
        # (실측: '컴퓨터공학전공 졸업요건'=0.860 → '…전공 교양 이수학점' 추가 시 0.121로 폭락 → 0건).
        rag_query = f"{dept_name} 졸업요건"
        rag_context, metadata = await self._search_rag(rag_query)

        # DB 요건도 없고 서술형 문서도 0건 = 이 학과에 대해 아는 게 없다. 그대로 LLM에 넘기면
        # 없는 학점·TOEIC 점수를 창작한다(메모리 기록: 호텔경영학과 사례). LLM을 건너뛴다.
        if rule is None and metadata.get("rag_empty"):
            print(f"[Graduation] ⚠️ '{dept_name}' DB요건·문서 모두 없음 → LLM 스킵(환각 방지)")
            return (
                f"죄송해요, {dept_name}의 졸업요건 자료를 찾지 못했어요. "
                "학과 사무실이나 학교 홈페이지에서 확인해 주세요.",
                metadata,
            )
        # 요건 수치(DB)는 있는데 서술형 문서만 0건이면, '못 찾음' 문자열이 컨텍스트로 들어가
        # LLM이 서술형 규정을 창작할 수 있다. 학점 기준만 쓰도록 명시적 '없음' 신호로 바꾼다.
        if metadata.get("rag_empty"):
            rag_context = "(서술형 졸업규정 문서 없음 — 위 학점 기준 외에는 추측하지 말 것)"

        prompt = GRADUATION_OTHER_DEPT_PROMPT.format(
            dept=dept_name, req_context=req_context, rag_context=rag_context, question=question,
        )
        # 구조적 졸업 답변은 실행마다 흔들리면 안 되므로 결정론적으로(temp 0.0) 생성.
        # (0.3에서 '학점 기준' 섹션이 통째로 누락되는 변덕이 관측됨)
        result = await llm_service.answer(prompt, max_tokens=1024, temperature=0.0)
        result = clean_answer(result)

        # 파일 제안은 '완성된 답변' 기준(질문 기준은 신호가 약함). graduation은 현재 파일이 없어
        # 결과가 늘 비지만, 파일이 추가되면 자동으로 동작한다.
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(
            None, match_relevant_files, result, AVAILABLE_FILES.get("graduation", [])
        )
        if files:
            metadata["files_to_offer"] = [Path(f).stem for f in files]

        return result, metadata

    async def _answer_my_dept(self, question: str, dept_id: int, dept_name: str,
                             admission_year: int, student_id: int, db: AsyncSession) -> tuple[str, dict]:
        """내 학과 졸업 답변 — 졸업요건(학점 DB + 서술형 문서) + 본인 '학점' 이수현황을 함께.
        영어·자격증·토익·졸업가능여부는 현황으로 판단 안 하고 요건 안내에만 포함(DB 미추적)."""
        from pathlib import Path
        from app.services.file_service import AVAILABLE_FILES
        from app.utils.file_matcher import match_relevant_files, clean_answer

        # 1) 요건 학점 (DB rule) — 내 학번 요건이 없으면 가장 가까운 연도로 폴백
        rule, actual_year, is_fallback = await self._resolve_requirement_rule(db, dept_id, admission_year)
        if rule:
            fallback_note = (
                f"※ 요청하신 {admission_year}년 졸업요건은 등록돼 있지 않습니다. "
                f"가장 가까운 {actual_year}년 졸업요건으로 대신 안내합니다.\n"
            ) if is_fallback else ""
            req_context = (
                fallback_note +
                f"전공 최소 이수학점: {rule.min_credits_major}학점\n"
                f"교양 최소 이수학점: {rule.min_credits_liberal}학점\n"
                f"졸업 총 이수학점: {rule.min_credits_total}학점\n"
                f"영어 공인성적: 필요"
            )
        else:
            req_context = f"{dept_name} {admission_year}학번 졸업요건 정보가 DB에 등록되어 있지 않습니다."

        # 2) 서술형 요건 (리랭커 노이즈 방지 위해 깔끔한 학과 키워드로 검색)
        # '전공 교양 이수학점'을 붙이면 리랭커가 학과 특이성을 잃어 0건이 된다(위 _answer_dept_requirement 주석 참조).
        rag_context, metadata = await self._search_rag(f"{dept_name} 졸업요건")
        # 서술형 문서가 0건이면 '못 찾음' 문자열이 컨텍스트로 들어가 LLM이 서술형 규정을
        # 창작한다. 이 경로는 학점 요건(DB)·개인 현황이 유효하므로 LLM은 호출하되(그 수치는
        # 보여줘야 한다), 서술형 부분만 명시적 '없음' 신호로 눌러 창작을 막는다.
        # (학과명 빼고 공통 문서로 폴백하는 방식은 편입생 이수학점표가 딸려와 '나 졸업 가능해?'에
        #  안 물어본 편입 정보가 가득 나오는 부작용이 있어 롤백했다 — 정확성 우선.)
        if metadata.get("rag_empty"):
            rag_context = "(서술형 졸업규정 문서 없음 — 위 학점 기준·이수현황 외에는 추측하지 말 것)"

        # 3) 본인 '학점' 이수현황 (영어·졸업가능여부 등은 제외)
        report = await self._check_graduation_status(db, student_id)
        if "error" in report:
            status_context = report["error"]
        else:
            mj = max(0, report["req_major"] - report["earned_major"])
            lb = max(0, report["req_liberal"] - report["earned_liberal"])
            tt = max(0, report["total_required"] - report["total_earned"])
            status_context = (
                f"전공: {report['earned_major']} / {report['req_major']} (부족 {mj})\n"
                f"교양: {report['earned_liberal']} / {report['req_liberal']} (부족 {lb})\n"
                f"총: {report['total_earned']} / {report['total_required']} (부족 {tt})"
            )

        prompt = GRADUATION_MY_DEPT_PROMPT.format(
            dept=dept_name, req_context=req_context, rag_context=rag_context,
            status_context=status_context, question=question,
        )
        result = await llm_service.answer(prompt, max_tokens=1024, temperature=0.0)
        result = clean_answer(result)

        # 파일 제안은 '완성된 답변' 기준. graduation은 현재 파일이 없어 결과가 늘 빈다.
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(
            None, match_relevant_files, result, AVAILABLE_FILES.get("graduation", [])
        )
        if files:
            metadata["files_to_offer"] = [Path(f).stem for f in files]

        return result, metadata

    async def answer_graduation(self, question: str, student_id: int, db: AsyncSession) -> str:
        answer, _ = await self.answer_graduation_with_metadata(question, student_id, db)
        return answer

    async def get_status_answer(self, student_id: int, db: AsyncSession) -> str:
        """명시적 '내 졸업 현황' 조회 — 버튼/메뉴에서 호출. 로그인 학생 본인 학과 기준.

        채팅 분류기를 거치지 않으므로 다른 학과 질문과 섞이지 않는다.
        """
        return await self._answer_from_db("내 졸업 요건 충족 현황을 알려줘", student_id, db)

    async def get_status_report(self, current_user: Student, db: AsyncSession) -> dict:
        """학점 진행률 위젯용 — 이수/필요/남은 학점(구조화 데이터, LLM 미사용).

        백분율·졸업시험·영어인증 등은 제외하고 순수 학점만 반환한다
        (위젯이 '학점 진행률'로만 표기 — 졸업 전체 충족과 혼동 방지).
        학생이 아니거나 데이터 없음/오류면 위젯 숨김 신호({available: False})를 반환한다
        (사이드바가 깨지지 않도록 예외를 밖으로 던지지 않음)."""
        # 학생이 아니면(관리자 등) 학점 데이터 없음 → 위젯 숨김
        if getattr(current_user, "role", None) != "student":
            return {"available": False, "reason": "not_student"}
        try:
            report = await self._check_graduation_status(db, current_user.id)
        except Exception:
            import traceback
            traceback.print_exc()
            return {"available": False}
        if "error" in report:
            return {"available": False}
        remaining = max(0, report["total_required"] - report["total_earned"])
        categories = [
            {"name": "전공", "earned": report["earned_major"],   "required": report["req_major"]},
            {"name": "교양", "earned": report["earned_liberal"], "required": report["req_liberal"]},
        ]
        # 일반(일반선택): 최소 요건이 없으면(required=0) '0/0 충족'처럼 무의미하게 보임 →
        # 이수 학점이 있거나 요건이 있을 때만 항목 표시. (이수 학점은 총 이수학점엔 이미 포함)
        if report["earned_general"] > 0 or report["req_general"] > 0:
            categories.append(
                {"name": "일반", "earned": report["earned_general"], "required": report["req_general"]}
            )
        # 트랙(다전공): 트랙 요건이 있는 학과만 표시 (전공·교양과 나란한 독립 이수구분)
        if report.get("req_track") is not None:
            categories.append(
                {"name": "트랙", "earned": report["earned_track"], "required": report["req_track"]}
            )
        return {
            "available": True,
            "dept_name": report.get("dept_name"),
            "total_earned": report["total_earned"],
            "total_required": report["total_required"],
            "remaining": remaining,
            "categories": categories,
            "student_no": current_user.student_no,
        }

    async def _classify_question(self, question: str) -> str:
        """임베딩 유사도로 질문 유형 분류 (personal / document / both)"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _graduation_classifier.classify, question)

    # =============================================
    # 경로 1: 개인 현황 (DB)
    # =============================================

    async def _answer_from_db(self, question: str, student_id: int, db: AsyncSession) -> str:
        report = await self._check_graduation_status(db, student_id)
        if "error" in report:
            return report["error"]
        context = self._build_db_context(report)
        prompt = self._build_db_prompt(question, context)
        return await llm_service.answer(prompt, max_tokens=1024)

    # =============================================
    # 경로 2: 공식 문서 (RAG)
    # =============================================

    async def _answer_from_rag(self, question: str) -> tuple[str, dict]:
        import time
        t1 = time.time()
        rag_context, metadata = await self._search_rag(question)
        print(f"[Graduation] RAG 검색 완료: {time.time()-t1:.1f}초")

        from app.services.file_service import AVAILABLE_FILES
        from app.utils.file_matcher import match_relevant_files, clean_answer
        from pathlib import Path
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(
            None, match_relevant_files, question, AVAILABLE_FILES.get("graduation", [])
        )

        # 검색 0건이면 LLM을 호출하지 않는다. "못 찾음" 문자열을 컨텍스트로 받은 LLM이 근거 없이
        # 절차·수치를 창작하기 때문(rag_general의 동일 가드를 여기에도 세운다).
        if metadata.get("rag_empty"):
            print("[Graduation] ⚠️ RAG 0건 → LLM 스킵(환각 방지)")
            if files:
                metadata["files_to_offer"] = [Path(f).stem for f in files]
                stems = "\n".join(f"- {Path(f).stem}" for f in files)
                return (
                    "질문하신 내용은 챗봇이 정리해 둔 자료에는 없지만, 관련 안내 파일이 준비되어 있어요.\n\n"
                    f"{stems}\n\n파일 드릴까요?",
                    metadata,
                )
            return (
                "죄송해요, 졸업 관련 해당 내용의 공식 자료를 찾지 못했어요. "
                "조금 더 구체적으로 질문해 주시거나 학과 사무실에 문의해 주세요.",
                metadata,
            )

        prompt = self._build_rag_prompt(question, rag_context)
        t2 = time.time()
        result = await llm_service.answer(prompt)
        print(f"[Graduation] LLM 추론 완료: {time.time()-t2:.1f}초")

        # 파일 제안은 임베딩 필터(match_relevant_files) 결과로 확정. LLM 태그는 화면에서 제거만.
        result = clean_answer(result)
        if files:
            metadata["files_to_offer"] = [Path(f).stem for f in files]

        return result, metadata

    # =============================================
    # 경로 3: 개인 현황 + 공식 문서 (DB + RAG)
    # =============================================

    async def _answer_from_db_and_rag(self, question: str, student_id: int, db: AsyncSession) -> tuple[str, dict]:
        report, rag_data = await asyncio.gather(
            self._check_graduation_status(db, student_id),
            self._search_rag(question),
        )
        rag_context, metadata = rag_data
        db_context = report.get("error") if "error" in report else self._build_db_context(report)

        from app.services.file_service import AVAILABLE_FILES
        from app.utils.file_matcher import match_relevant_files, clean_answer
        from pathlib import Path
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(
            None, match_relevant_files, question, AVAILABLE_FILES.get("graduation", [])
        )

        prompt = self._build_combined_prompt(question, db_context, rag_context)
        # 구조적 졸업 답변은 실행마다 흔들리면 안 되므로 결정론적으로(temp 0.0) 생성.
        # (0.3에서 '학점 기준' 섹션이 통째로 누락되는 변덕이 관측됨)
        result = await llm_service.answer(prompt, max_tokens=1024, temperature=0.0)

        # 파일 제안은 임베딩 필터(match_relevant_files) 결과로 확정. LLM 태그는 화면에서 제거만.
        result = clean_answer(result)
        if files:
            metadata["files_to_offer"] = [Path(f).stem for f in files]

        return result, metadata

    async def _search_rag(self, question: str) -> tuple[str, dict]:
        """RAG 검색 (별도 스레드 실행 - LLM과 충돌 방지)"""
        loop = asyncio.get_event_loop()
        context, results = await loop.run_in_executor(
            None,
            lambda: rag_service.search_context_with_results(
                question, topic="graduation", original_question=question
            ),
        )
        if context:
            # 컨텍스트를 과도하게(500자) 자르면 얇은 근거로 LLM이 빈자리를 창작(fabrication)한다.
            # (예: "호텔경영학과 졸업요건" → 없는 학점·TOEIC 숫자 지어냄)
            # 리트리버가 이미 MAX_CHUNKS/MAX_MERGED_LENGTH로 상한을 두므로 넉넉히 사용한다.
            return context[:2000], rag_service.primary_metadata(results, topic="graduation")
        # 검색 0건. 호출부가 LLM 호출을 건너뛰도록 rag_empty 플래그를 남긴다 — 이 신호가 없으면
        # "관련 공식 문서를 찾지 못했습니다."가 컨텍스트로 LLM에 들어가 빈칸을 창작한다
        # (실측: '조기졸업' 답변에 근거 없는 '학부모와 상담' 등장, src=None).
        return (
            "관련 공식 문서를 찾지 못했습니다.",
            {"source": None, "source_file": None, "topic": "graduation", "rag_empty": True},
        )

    # =============================================
    # DB 조회
    # =============================================

    async def _get_student(self, db: AsyncSession, student_id: int):
        """학생 정보 + 학과명 조회"""
        result = await db.execute(
            select(Student, Department.name)
            .join(Department, Student.dept_id == Department.id)
            .where(Student.id == student_id)
        )
        row = result.one_or_none()
        if row is None:
            return None, None
        return row[0], row[1]  # (Student, dept_name)

    async def _get_requirement_rule(self, db: AsyncSession, dept_id: int, admission_year: int):
        """졸업요건 규칙 조회"""
        set_result = await db.execute(
            select(RequirementSet).where(
                RequirementSet.dept_id == dept_id,
                RequirementSet.admission_year == admission_year
            )
        )
        req_set = set_result.scalar_one_or_none()
        if not req_set:
            return None, None

        rule_result = await db.execute(
            select(RequirementRule).where(RequirementRule.set_id == req_set.id)
        )
        return req_set, rule_result.scalar_one_or_none()

    async def _resolve_requirement_rule(self, db: AsyncSession, dept_id: int, requested_year: int):
        """요청 연도로 요건을 찾되, 없으면 그 학과에서 '가장 가까운' 연도로 폴백한다.

        반환 (rule, actual_year, is_fallback):
          - rule: 사용할 RequirementRule (학과에 등록된 요건이 아예 없으면 None)
          - actual_year: 실제로 사용한 연도 (폴백이면 대체 연도)
          - is_fallback: 요청 연도가 없어 다른 연도로 대체했는지

        '가장 가까운 연도' = 요청 연도 이하 중 최신(가장 가까운 과거 코호트).
        요청 연도가 등록된 모든 연도보다 이르면 가장 오래된 연도를 쓴다.
        (예: 2028 요청 + DB에 2022~2025 등록 → 2025 / 2019 요청 → 2022)
        즉 '2028학번 요건 없음' 같은 경우 조용히 아무거나 주는 대신, 가장 최근 요건으로
        폴백하고 호출부가 그 사실을 답변에 자연스럽게 밝히도록 is_fallback을 돌려준다.
        """
        # 1) 정확일치 우선
        _set, rule = await self._get_requirement_rule(db, dept_id, requested_year)
        if rule:
            return rule, requested_year, False

        # 2) 그 학과에 등록된 연도 전부 조회
        years = (await db.execute(
            select(RequirementSet.admission_year).where(RequirementSet.dept_id == dept_id)
        )).scalars().all()
        years = sorted({int(y) for y in years if y is not None})
        if not years:
            return None, requested_year, False   # 학과 자체에 요건 없음 → 기존 환각방지 스킵이 처리

        # 3) 가장 가까운 연도 선택 후 그 규칙 조회
        le = [y for y in years if y <= requested_year]
        actual_year = le[-1] if le else years[0]
        _set2, rule2 = await self._get_requirement_rule(db, dept_id, actual_year)
        if rule2:
            return rule2, actual_year, True
        return None, requested_year, False       # 대체 연도에도 유효 규칙 없음 → 폴백 취급 안 함

    async def _get_earned_credits(self, db: AsyncSession, student_id: int) -> dict:
        """이수 학점 카테고리별 합산

        재수강 대응: student_course에 (student_id, course_code) 유니크 제약이 없어
        같은 과목이 여러 행일 수 있으므로, 통과한 과목 코드를 중복 제거(distinct)한 뒤
        과목당 학점을 한 번만 합산한다. (재수강 과목 학점 이중 계산 방지)
        """
        # 학생이 통과한 과목 코드 목록 (중복 제거)
        passed_codes = (
            select(distinct(StudentCourse.course_code))
            .where(
                StudentCourse.student_id == student_id,
                StudentCourse.is_passed == True,
            )
            .scalar_subquery()
        )
        result = await db.execute(
            select(Course.category, func.sum(Course.credits))
            .where(Course.code.in_(passed_codes))
            .group_by(Course.category)
        )
        return {row[0]: float(row[1]) for row in result.all()}

    async def _has_english_cert(self, db: AsyncSession, student_id: int) -> bool:
        """영어 공인성적 보유 여부 확인"""
        result = await db.execute(
            select(StudentAchievement).where(
                StudentAchievement.student_id == student_id
            )
        )
        achievements = result.scalars().all()
        return any(a.type == "english_cert" and a.value == "PASS" for a in achievements)

    # =============================================
    # 졸업 여부 계산
    # =============================================

    async def _check_graduation_status(self, db: AsyncSession, student_id: int) -> dict:
        """졸업 요건 충족 여부 종합 계산"""
        is_graduated = True
        insufficient_details = []

        # 학생 조회
        student, dept_name = await self._get_student(db, student_id)
        if not student:
            return {"error": "등록된 학생을 찾을 수 없습니다."}

        # 입학연도 추출
        try:
            admission_year = int(student.student_no[:4])
        except (ValueError, TypeError, IndexError):
            admission_year = 2026
            print(f"[Warning] 입학연도 추출 실패, 2026으로 설정 (학번: {student.student_no})")

        # 졸업요건 조회
        req_set, rule = await self._get_requirement_rule(db, student.dept_id, admission_year)
        if not req_set:
            return {"error": f"{dept_name}({admission_year}년도 입학) 졸업요건 정보가 등록되어 있지 않습니다."}
        if not rule:
            return {"error": "졸업요건 세부 규칙이 설정되어 있지 않습니다."}

        # 이수 학점 계산 (DB category 값: "전공필수", "교양필수")
        passed_credits = await self._get_earned_credits(db, student_id)
        earned_major   = (passed_credits.get("전공필수", 0.0) + passed_credits.get("전공선택", 0.0))
        earned_liberal = (passed_credits.get("교양필수", 0.0) + passed_credits.get("교양선택", 0.0))
        earned_general = passed_credits.get("일반", 0.0)

        # 트랙(다전공): 전공·교양과 나란한 '독립 이수구분'. category "트랙" 집계로 계산.
        # req_track이 None인 학과는 트랙 요건 없음(트랙 과목 없으면 earned_track=0).
        req_track    = rule.min_credits_track
        earned_track = passed_credits.get("트랙", 0.0)

        # 총 이수학점 = 전공+교양+일반+트랙 (모든 이수구분 학점 합산 — 트랙도 포함해야 증발 안 함)
        total_earned = earned_major + earned_liberal + earned_general + earned_track

        # 학점 충족 여부 확인
        if earned_major < rule.min_credits_major:
            is_graduated = False
            insufficient_details.append(f"전공 {rule.min_credits_major - earned_major}학점 부족")

        if earned_liberal < rule.min_credits_liberal:
            is_graduated = False
            insufficient_details.append(f"교양 {rule.min_credits_liberal - earned_liberal}학점 부족")

        if earned_general < rule.min_credits_general:
            is_graduated = False
            insufficient_details.append(f"일반 {rule.min_credits_general - earned_general}학점 부족")

        if total_earned < rule.min_credits_total:
            is_graduated = False
            insufficient_details.append(f"총학점 {rule.min_credits_total - total_earned}학점 부족")

        # 트랙 부족 판정 — 트랙 요건이 있는 학과만
        if req_track is not None and earned_track < req_track:
            is_graduated = False
            insufficient_details.append(f"트랙 {req_track - earned_track}학점 부족")

        # 영어 인증 확인
        english_cert_passed = await self._has_english_cert(db, student_id)
        if not english_cert_passed:
            is_graduated = False
            insufficient_details.append("영어 공인성적 미취득")

        return {
            "is_graduated":       is_graduated,
            "english_cert_passed": english_cert_passed,
            "dept_name":          dept_name,
            "earned_major":       earned_major,
            "req_major":          rule.min_credits_major,
            "earned_liberal":     earned_liberal,
            "req_liberal":        rule.min_credits_liberal,
            "earned_general":     earned_general,
            "req_general":        rule.min_credits_general,
            "earned_track":       earned_track,
            "req_track":          req_track,
            "total_earned":       total_earned,
            "total_required":     rule.min_credits_total,
            "insufficient_details": insufficient_details,
        }

    # =============================================
    # LLM 프롬프트 생성
    # =============================================

    def _build_db_context(self, report: dict) -> str:
        """DB 조회 결과를 LLM 컨텍스트 문자열로 변환"""
        status = "졸업 가능" if report["is_graduated"] else "졸업 불가"

        # 초과 이수 시 음수가 나오지 않도록 0으로 클램프
        major_short   = max(0, report['req_major'] - report['earned_major'])
        liberal_short = max(0, report['req_liberal'] - report['earned_liberal'])
        general_short = max(0, report['req_general'] - report['earned_general'])
        total_short   = max(0, report['total_required'] - report['total_earned'])

        dept_name = report.get("dept_name", "")
        english_status = "취득 완료" if report.get("english_cert_passed") else "미취득"

        # 트랙(다전공): 요건이 있는 학과만 표시
        track_line = ""
        if report.get("req_track") is not None:
            track_short = max(0, report["req_track"] - report["earned_track"])
            track_line = (
                f"트랙 학점: 현재 {report['earned_track']}학점 이수, "
                f"졸업에 필요한 학점 {report['req_track']}학점, 아직 부족한 학점 {track_short}학점\n"
            )

        return (
            f"[학생 졸업요건 조회 결과 - 아래 수치는 정확한 DB 데이터임]\n"
            f"학과: {dept_name}\n"
            f"졸업 가능 여부: {status}\n\n"
            f"전공 학점: 현재 {report['earned_major']}학점 이수, 졸업에 필요한 학점 {report['req_major']}학점, 아직 부족한 학점 {major_short}학점\n"
            f"교양 학점: 현재 {report['earned_liberal']}학점 이수, 졸업에 필요한 학점 {report['req_liberal']}학점, 아직 부족한 학점 {liberal_short}학점\n"
            f"일반 학점: 현재 {report['earned_general']}학점 이수, 졸업에 필요한 학점 {report['req_general']}학점, 아직 부족한 학점 {general_short}학점\n"
            f"{track_line}"
            f"총 이수 학점: 현재 {report['total_earned']}학점 이수, 졸업에 필요한 총 학점 {report['total_required']}학점, 아직 부족한 학점 {total_short}학점\n"
            f"영어 공인성적: {english_status}\n"
        )

    def _build_db_prompt(self, question: str, context: str) -> str:
        return GRADUATION_DB_PROMPT.format(context=context, question=question)

    def _build_rag_prompt(self, question: str, rag_context: str) -> str:
        return GRADUATION_RAG_PROMPT.format(rag_context=rag_context, question=question)

    def _build_combined_prompt(self, question: str, db_context: str, rag_context: str) -> str:
        return GRADUATION_COMBINED_PROMPT.format(db_context=db_context, rag_context=rag_context, question=question)


# 싱글톤 인스턴스
graduation_service = GraduationService()
