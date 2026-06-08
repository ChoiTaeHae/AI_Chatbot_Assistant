from app.agents.intent import IntentType

GRADUATION_KEYWORDS  = ["졸업", "학점", "필수과목", "전공필수", "교양필수", "이수", "졸업요건", "졸업조건", "졸업학점"]
SCHEDULE_KEYWORDS    = ["수강신청", "학사일정", "시험", "중간고사", "기말고사", "방학", "개강", "종강", "일정", "언제", "기간", "학사"]
LEAVE_KEYWORDS       = ["휴학", "복학", "군휴학", "휴학신청", "휴학절차", "휴학방법", "창업휴학", "육아휴학", "휴학기간"]
CAMPUS_KEYWORDS      = ["건물", "위치", "어디", "캠퍼스", "강의실", "학과사무실", "도서관", "체육관", "식당", "호실", "층"]
SCHOLARSHIP_KEYWORDS = ["장학금", "장학", "장학생", "장학신청", "성적장학", "국가장학", "장학금신청", "장학금조건", "장학금지원"]


def classify_intent(question: str) -> IntentType:
    for keyword in GRADUATION_KEYWORDS:
        if keyword in question:
            return IntentType.GRADUATION
    for keyword in SCHEDULE_KEYWORDS:
        if keyword in question:
            return IntentType.SCHEDULE
    for keyword in LEAVE_KEYWORDS:
        if keyword in question:
            return IntentType.LEAVE
    for keyword in CAMPUS_KEYWORDS:
        if keyword in question:
            return IntentType.CAMPUS
    for keyword in SCHOLARSHIP_KEYWORDS:
        if keyword in question:
            return IntentType.SCHOLARSHIP
    return IntentType.GENERAL
