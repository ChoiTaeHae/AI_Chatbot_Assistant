import asyncio

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.models.DB_Table import (
    Student, RequirementSet, RequirementRule,
    StudentAchievement, Course, StudentCourse
)
from app.services.chat_service import chat_service
from app.services.rag_service import rag_service

# 개인 현황 질문 키워드 (DB 조회 경로)
_PERSONAL_KEYWORDS = ["내", "나의", "나는", "나", "제", "저의", "저는", "저", "내가", "제가", "내 졸업", "제 졸업"]

# 공식 문서 질문 키워드 (RAG 경로)
_DOCUMENT_KEYWORDS = ["방법", "절차", "서류", "신청", "어떻게", "어디서", "기간", "일정", "규정", "제출", "조건이란", "요건이란"]


class GraduationService:

    # =============================================
    # 메인 진입점
    # =============================================

    async def answer_graduation(self, question: str, student_id: int, db: AsyncSession) -> str:
        """Agent가 호출하는 메인 함수 - 질문 유형에 따라 DB/RAG/둘 다 경로 선택"""
        question_type = self._classify_question(question)
        print(f"[Graduation] 질문 유형: {question_type}")

        if question_type == "personal":
            return await self._answer_from_db(question, student_id, db)

        elif question_type == "document":
            return await self._answer_from_rag(question)

        else:  # both
            return await self._answer_from_db_and_rag(question, student_id, db)

    def _classify_question(self, question: str) -> str:
        """personal: 개인 현황 / document: 공식 문서 / both: 둘 다"""
        is_personal = any(kw in question for kw in _PERSONAL_KEYWORDS)
        is_document = any(kw in question for kw in _DOCUMENT_KEYWORDS)

        if is_personal and is_document:
            return "both"
        if is_personal:
            return "personal"
        return "document"  # 기본값: 공식 문서 RAG 검색

    # =============================================
    # 경로 1: 개인 현황 (DB)
    # =============================================

    async def _answer_from_db(self, question: str, student_id: int, db: AsyncSession) -> str:
        report = await self._check_graduation_status(db, student_id)
        if "error" in report:
            return report["error"]
        context = self._build_db_context(report)
        prompt = self._build_db_prompt(question, context)
        return await chat_service.answer(prompt)

    # =============================================
    # 경로 2: 공식 문서 (RAG)
    # =============================================

    async def _answer_from_rag(self, question: str) -> str:
        rag_context = await self._search_rag(question)
        prompt = self._build_rag_prompt(question, rag_context)
        return await chat_service.answer(prompt)

    # =============================================
    # 경로 3: 개인 현황 + 공식 문서 (DB + RAG)
    # =============================================

    async def _answer_from_db_and_rag(self, question: str, student_id: int, db: AsyncSession) -> str:
        report, rag_context = await asyncio.gather(
            self._check_graduation_status(db, student_id),
            self._search_rag(question),
        )
        db_context = report.get("error") if "error" in report else self._build_db_context(report)
        prompt = self._build_combined_prompt(question, db_context, rag_context)
        return await chat_service.answer(prompt)

    async def _search_rag(self, question: str) -> str:
        """RAG 검색 (별도 스레드 실행 - LLM과 충돌 방지)"""
        loop = asyncio.get_event_loop()
        context = await loop.run_in_executor(None, rag_service.search_context, question)
        return context or "관련 공식 문서를 찾지 못했습니다."

    # =============================================
    # DB 조회
    # =============================================

    async def _get_student(self, db: AsyncSession, student_id: int):
        """학생 정보 조회"""
        result = await db.execute(select(Student).where(Student.id == student_id))
        return result.scalar_one_or_none()

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
        """이수 학점 카테고리별 합산"""
        result = await db.execute(
            select(Course.category, func.sum(Course.credits))
            .join(StudentCourse, Course.code == StudentCourse.course_code)
            .where(
                StudentCourse.student_id == student_id,
                StudentCourse.is_passed == True
            )
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
        student = await self._get_student(db, student_id)
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
            return {"error": f"학과(ID: {student.dept_id}) {admission_year}년도 졸업요건이 없습니다."}
        if not rule:
            return {"error": "졸업요건 세부 규칙이 설정되어 있지 않습니다."}

        # 이수 학점 계산
        passed_credits = await self._get_earned_credits(db, student_id)
        earned_major   = passed_credits.get("major", 0.0)
        earned_liberal = passed_credits.get("liberal", 0.0)
        earned_general = passed_credits.get("general", 0.0)
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
        if not await self._has_english_cert(db, student_id):
            is_graduated = False
            insufficient_details.append("영어 공인성적 미취득")

        return {
            "is_graduated":       is_graduated,
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
        status = "가능 (졸업 요건 충족)" if report["is_graduated"] else "불가 (요건 미충족)"
        lacking = ", ".join(report["insufficient_details"]) if report["insufficient_details"] else "없음"

        return (
            f"[졸업 요건 조회 결과]\n"
            f"- 졸업 가능 여부: {status}\n"
            f"- 전공 학점: {report['earned_major']}학점 이수 / 졸업 요건: {report['req_major']}학점\n"
            f"- 교양 학점: {report['earned_liberal']}학점 이수 / 졸업 요건: {report['req_liberal']}학점\n"
            f"- 일반 학점: {report['earned_general']}학점 이수 / 졸업 요건: {report['req_general']}학점\n"
            f"- 총 이수 학점: {report['total_earned']}학점 / 총 필요 요건: {report['total_required']}학점\n"
            f"- 부족한 항목: {lacking}\n"
        )

    def _build_db_prompt(self, question: str, context: str) -> str:
        """DB 데이터 기반 프롬프트"""
        return (
            f"{context}\n\n"
            f"위 데이터는 DB에서 정확하게 계산된 100% 실제 데이터입니다.\n"
            f"임의로 수정하거나 추측하지 마세요.\n"
            f"학생 질문('{question}')에 대해 위 데이터를 기반으로 "
            f"친절하고 자세하게 설명하고 부족한 부분을 명확하게 안내해주세요."
        )

    def _build_rag_prompt(self, question: str, rag_context: str) -> str:
        """RAG 문서 기반 프롬프트"""
        return (
            f"[공식 졸업 관련 문서 검색 결과]\n"
            f"{rag_context}\n\n"
            f"위 내용은 학교 공식 문서에서 검색된 자료입니다.\n"
            f"검색된 내용을 벗어난 추측은 하지 마세요.\n"
            f"학생 질문('{question}')에 대해 위 문서를 근거로 "
            f"친절하고 명확하게 답변해주세요."
        )

    def _build_combined_prompt(self, question: str, db_context: str, rag_context: str) -> str:
        """DB + RAG 데이터 통합 프롬프트"""
        return (
            f"{db_context}\n\n"
            f"[공식 졸업 관련 문서 검색 결과]\n"
            f"{rag_context}\n\n"
            f"위 [졸업 요건 조회 결과]는 DB에서 계산된 실제 데이터이며, "
            f"[공식 문서]는 학교 규정집에서 검색된 내용입니다.\n"
            f"두 정보를 모두 활용하여 학생 질문('{question}')에 대해 "
            f"친절하고 자세하게 답변해주세요."
        )


# 싱글톤 인스턴스
graduation_service = GraduationService()
