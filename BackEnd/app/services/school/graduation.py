

import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, distinct

from app.models.DB_Table import (
    Student, Department, RequirementSet, RequirementRule,
    StudentAchievement, Course, StudentCourse
)
from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.rag.Embedding import BaaiEmbedding
from app.prompts import GRADUATION_DB_PROMPT, GRADUATION_RAG_PROMPT, GRADUATION_COMBINED_PROMPT

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


def _avg_normalize(vectors: list[list[float]]) -> list[float]:
    n, dim = len(vectors), len(vectors[0])
    avg = [sum(vectors[i][j] for i in range(n)) / n for j in range(dim)]
    norm = sum(x * x for x in avg) ** 0.5
    return [x / norm for x in avg] if norm > 0 else avg


class _GraduationClassifier:
    """졸업 질문 유형 임베딩 분류기 (personal / document / both)"""

    def __init__(self):
        self._embedding: BaaiEmbedding | None = None
        self._proto_vecs: dict[str, list[float]] | None = None

    @property
    def embedding(self) -> BaaiEmbedding:
        if self._embedding is None:
            self._embedding = BaaiEmbedding()
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
            self._proto_vecs[cat] = _avg_normalize(all_vecs[start:end])
        print(f"[GraduationClassifier] {len(categories)}개 유형 임베딩 완료")

    def classify(self, question: str) -> str:
        if self._proto_vecs is None:
            self._warmup()

        q_vec = self.embedding.embed_text(question)
        best_cat, best_score = "both", -1.0
        for cat, proto in self._proto_vecs.items():
            score = sum(x * y for x, y in zip(q_vec, proto))
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
        """Agent가 호출하는 메인 함수.

        채팅의 졸업 질문은 항상 **규정 문서(RAG)**로만 답한다.
        개인 이수현황(부족 학점)은 명시적 액션(GET /api/graduation/status)으로 분리했다.
        → 다른 학과 요건을 물었을 때 로그인 학생 본인의 개인현황이 섞여 나오는 환각을 방지.
        (student_id·db는 호출부 호환/로깅용으로 유지)
        """
        return await self._answer_from_rag(question)

    async def answer_graduation(self, question: str, student_id: int, db: AsyncSession) -> str:
        answer, _ = await self.answer_graduation_with_metadata(question, student_id, db)
        return answer

    async def get_status_answer(self, student_id: int, db: AsyncSession) -> str:
        """명시적 '내 졸업 현황' 조회 — 버튼/메뉴에서 호출. 로그인 학생 본인 학과 기준.

        채팅 분류기를 거치지 않으므로 다른 학과 질문과 섞이지 않는다.
        """
        return await self._answer_from_db("내 졸업 요건 충족 현황을 알려줘", student_id, db)

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
        from pathlib import Path
        files = AVAILABLE_FILES.get("graduation", [])
        files_list = "\n".join(f"- {Path(f).stem}" for f in files) if files else "없음"

        prompt = self._build_rag_prompt(question, rag_context, files_list)
        t2 = time.time()
        result = await llm_service.answer(prompt)
        print(f"[Graduation] LLM 추론 완료: {time.time()-t2:.1f}초")

        import re
        match = re.search(r'<FILES>(.*?)</FILES>', result)
        if match:
            files_str = match.group(1)
            metadata["files_to_offer"] = [f.strip() for f in files_str.split(',') if f.strip()]
            result = result[:match.start()] + result[match.end():]
            result = result.strip()

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
        from pathlib import Path
        files = AVAILABLE_FILES.get("graduation", [])
        files_list = "\n".join(f"- {Path(f).stem}" for f in files) if files else "없음"

        prompt = self._build_combined_prompt(question, db_context, rag_context, files_list)
        result = await llm_service.answer(prompt, max_tokens=1024)

        import re
        match = re.search(r'<FILES>(.*?)</FILES>', result)
        if match:
            files_str = match.group(1)
            metadata["files_to_offer"] = [f.strip() for f in files_str.split(',') if f.strip()]
            result = result[:match.start()] + result[match.end():]
            result = result.strip()

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
        return (
            "관련 공식 문서를 찾지 못했습니다.",
            {"source": None, "source_file": None, "topic": "graduation"},
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
        total_earned   = earned_major + earned_liberal + earned_general

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

        return (
            f"[학생 졸업요건 조회 결과 - 아래 수치는 정확한 DB 데이터임]\n"
            f"학과: {dept_name}\n"
            f"졸업 가능 여부: {status}\n\n"
            f"전공 학점: 현재 {report['earned_major']}학점 이수, 졸업에 필요한 학점 {report['req_major']}학점, 아직 부족한 학점 {major_short}학점\n"
            f"교양 학점: 현재 {report['earned_liberal']}학점 이수, 졸업에 필요한 학점 {report['req_liberal']}학점, 아직 부족한 학점 {liberal_short}학점\n"
            f"일반 학점: 현재 {report['earned_general']}학점 이수, 졸업에 필요한 학점 {report['req_general']}학점, 아직 부족한 학점 {general_short}학점\n"
            f"총 이수 학점: 현재 {report['total_earned']}학점 이수, 졸업에 필요한 총 학점 {report['total_required']}학점, 아직 부족한 학점 {total_short}학점\n"
            f"영어 공인성적: {english_status}\n"
        )

    def _build_db_prompt(self, question: str, context: str) -> str:
        return GRADUATION_DB_PROMPT.format(context=context, question=question)

    def _build_rag_prompt(self, question: str, rag_context: str, files_list: str = "없음") -> str:
        return GRADUATION_RAG_PROMPT.format(rag_context=rag_context, question=question, files_list=files_list)

    def _build_combined_prompt(self, question: str, db_context: str, rag_context: str, files_list: str = "없음") -> str:
        return GRADUATION_COMBINED_PROMPT.format(db_context=db_context, rag_context=rag_context, question=question, files_list=files_list)


# 싱글톤 인스턴스
graduation_service = GraduationService()
