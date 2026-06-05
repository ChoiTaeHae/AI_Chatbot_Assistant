from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.models.DB_Table import Student, RequirementSet, RequirementRule, StudentAchievement, Course, StudentCourse
from app.services.chat_service import chat_service

class GraduationService:

    async def answer_graduation(self, question: str, student_id: int, db: AsyncSession) -> str:
        """
        [최종 출구] SchoolAgent가 호출하는 메인 함수.
        1. DB 계산기로부터 팩트 리포트를 받아오고,
        2. 그 결과를 LLM(chat_service)에게 전달하여 다정한 대화체 문장으로 바꿉니다.
        """
        # 1. 학생의 이수 학점 계산
        report = await self._check_graduation_status(db, student_id)
        
        if "error" in report:
            return report["error"]
        
        #2. DB에서 뽑아온 숫자 정리
        context_str = (
            f"[데이터베이스 실시간 조회 결과]\n"
            f"- 졸업 가능 여부: {'충족 (졸업 가능)' if report['is_graduated'] else '미충족 (졸업 불가)'}\n"
            f"- 전공 학점: {report['earned_major']}학점 수강 / 졸업 기준: {report['req_major']}학점\n"
            f"- 교양 학점: {report['earned_liberal']}학점 수강 / 졸업 기준: {report['req_liberal']}학점\n"
            f"- 일반 학점: {report['earned_general']}학점 수강 / 졸업 기준: {report['req_general']}학점\n"
            f"- 총 취득 학점: {report['total_earned']}학점 / 총 요구 기준: {report['total_required']}학점\n"
            f"- 부족한 세부 항목 리스트: {', '.join(report['insufficient_details']) if report['insufficient_details'] else '없음'}\n"
        )

        # 3. Ollama에게 데이터 주입 및 대화 가공 요청
        prompt = (
            f"{context_str}\n\n"
            f"위의 [데이터베이스 실시간 조회 결과]는 시스템 DB에서 정확하게 계산된 100% 팩트 수치입니다.\n"
            f"이 수치들을 절대로 임의로 수정하거나 조작하지 마세요.\n"
            f"학생의 질문('{question}')에 대해, 위의 팩트 데이터를 기반으로 대학 학사지원처 조교처럼 친절하고 상냥한 존댓말로 요약 브리핑 답변을 작성해 주세요."
        )

        return await chat_service.answer(prompt)

    async def _check_graduation_status(self, db : AsyncSession, student_id: int) -> dict:
        
        """
        [DB 학점 계산기]
        """
        is_graduated = True
        insufficient_details = []

        #단계 1 : 학생 테이블에서 학과 및 입학년도 파악
        student_query = await db.execute(select(Student).where(Student.id == student_id))
        student = student_query.scalar_one_or_none()
        if not student :
            return {"error": "시스템에 등록되지 않은 학번입니다."}

        #학번 앞 4자리를 추출하여 입학년도로 변환
        try:
            admission_year = int(student.student_no[:4])
        except (ValueError, TypeError, IndexError):
            admission_year = 2026 #  학번이 일치하지 않을 경우, 가장 최신 졸업 요건을 적용 (2026년 입학 기준)
            print(f"[Warning] 학번 형식이 올바르지 않아 입학년도를 2026으로 가정합니다. (학번: {student.student_no})")

        # 단계 2 추출 입학년도로 졸업 요건 세트의 ID 찾기
        set_query = await db.execute(
            select(RequirementSet).where(
                RequirementSet.dept_id == student.dept_id,
                RequirementSet.admission_year == admission_year
            )
        )
        req_set = set_query.scalar_one_or_none()
        if not req_set :
            return {"error": f"해당학과(ID : {student.dept_id}) 및 {admission_year} 학번에 매칭되는 졸업 요건 기준이 DB에 존재하지 않습니다."}
        
        # 단계 3 : 찾은 세트 ID를 가지고 세부 규칙 기준 점수들 가져오기
        rule_query = await db.execute(
            select (RequirementRule).where(RequirementRule.set_id == req_set.id)
        )
        rule = rule_query.scalar_one_or_none()
        if not rule:
            return {"error" : "학과별 세부 졸업 기준 학점 (Rule)이 설정되어 있지 않습니다."}
        
        # 단계 4 : 학생이 이수한 과목들의 학점을 카테고리 별로 합산 (SUM)

        # TODO : StudentCourse 테이블이 완성되면, 아래 쿼리를 해당 테이블로 수정해야 합니다.
        # SQL: SELECT course.category, SUM(course.credits) FROM student_course ... GROUP BY category
            # (아래 코드는 student_course 테이블을 DB_Table.py에 클래스로 선언하면 즉시 활성화됩니다.)
        credits_query = await db.execute(
            select(Course.category, func.sum(Course.credits))
            .join(StudentCourse, Course.code == StudentCourse.course_code)
            .where(StudentCourse.student_id == student_id, StudentCourse.is_passed == True) # 패스한 과목만 합산
            .group_by(Course.category)
        )
        
        passed_credits = {row[0]: float(row[1]) for row in credits_query.all()}
        

        earned_major = passed_credits.get("major", 0.0)      # 취득 전공
        earned_liberal = passed_credits.get("liberal", 0.0)  # 취득 교양
        earned_general = passed_credits.get("general", 0.0)  # 취득 일반
        total_earned = earned_major + earned_liberal + earned_general # 총 취득
        
        # 단계 5 : DB에서 가져온 rule과 학생의 취득 학점 비교 연산

        if earned_major < rule.min_credits_major:
            is_graduated = False
            insufficient_details.append(f"전공 최소 기준에서 {rule.min_credits_major - earned_major}학점 부족")

        if earned_liberal < rule.min_credits_liberal:
            is_graduated = False
            insufficient_details.append(f"교양 최소 기준에서 {rule.min_credits_liberal - earned_liberal}학점 부족")

        if earned_general < rule.min_credits_general:
            is_graduated = False
            insufficient_details.append(f"일반 최소 기준에서 {rule.min_credits_general - earned_general}학점 부족")

        if total_earned < rule.min_credits_total:
            is_graduated = False
            insufficient_details.append(f"졸업 총 기준학점에서 {rule.min_credits_total - total_earned}학점 부족")

        
        # 단계 6 : 학생 실적(StudentAchievevment) 테이블에서 비과목 요건 (영어/ 논문) 검증

        achieve_query = await db.execute(
            select(StudentAchievement).where(
                StudentAchievement.student_id == student_id
            )
        )
        achievements = achieve_query.scalars().all()

        has_english_cert = False
        for ach in achievements:
            if ach.type == "english_cert" and ach.value == "PASS":
                has_english_cert = True
        
        if not has_english_cert:
            is_graduated = False
            insufficient_details.append("외국어 인증성적(토익 등) 미충족")

            # 단계 7 : 최종

        return {
               "is_graduated": is_graduated,
                "earned_major": earned_major,
                "req_major": rule.min_credits_major,
                "earned_liberal": earned_liberal,
                "req_liberal": rule.min_credits_liberal,
                "earned_general": earned_general,
                "req_general": rule.min_credits_general,
                "total_earned": total_earned,
                "total_required": rule.min_credits_total,
                "insufficient_details": insufficient_details
            } 

graduation_service = GraduationService()