from datetime import date
from app.core.Database import SessionLocal

async def answer_schedule_question(question : str) -> str :
    """학사일정 관련 질문을 처리하고 적절한 안내 응답을 반환합니다."""

    #질문에서 키워트 추출함
    schedule_type = await _extract_schedule_type(question)
    if not schedule_type :
        return "어떤 일정이 궁금하신지(예 : 시험, 수강신청, 휴학, 개강, 휴강 등) 구체적으로 말씀해주세요."
    
    #현재 날짜 기준
    today = date.today()

    #DB 마스터키 발급
    db = SessionLocal()
    try :
        upcoming_schedules = await get_upcoming_schedule(db=db, keyword=schedule_type)

        if not upcoming_schedules :
            return f"현재 예정된 {schedule_type} 일정이 없습니다."
    
        #가장 가까운 일정 순으로 오름차순 정렬
        upcoming_schedules.sort(key=lambda x : x["start_date"])
        target_schedule = upcoming_schedules[0]

        #응답 문자열 포맷팅
        start_str = target_schedule["start_date"].strftime("%m월 %d일")
        end_str = target_schedule["end_date"].strftime("%m월 %d일")

        if start_str == end_str :
            return f"{target_schedule['event_name']}는 {start_str}입니다."
        else :
            return f"{target_schedule['event_name']}는 {start_str}~{end_str}입니다."
    finally :
        db.close()  #DB연결 종료
    
async def _extract_schedule_type(question : str) -> str:
    prompt = f""" 
    사용자의 질문 : "{question}"
    핵심 키워드 :
    """

    try :
        #LLM에게 프롬프트 전송해서 답 받기
        response = await chat_service.answer(prompt)
        return response.strip().replace(".", "").replace("'","").replace('"',"")
    except :
        return ""