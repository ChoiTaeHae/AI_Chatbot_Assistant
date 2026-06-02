from app.agent.intent import IntentType


# 졸업요건 관련 키워드
GRADUATION_KEYWORDS = [
    "졸업", "학점", "필수과목", "전공필수", "교양필수",
    "이수", "졸업요건", "졸업조건", "졸업학점",
]

# 학사일정 관련 키워드
SCHEDULE_KEYWORDS = [
    "수강신청", "학사일정", "시험", "중간고사", "기말고사",
    "방학", "개강", "종강", "휴강", "공휴일", "일정", "언제",
]


def classify_intent(question: str) -> IntentType:
    """질문에서 키워드를 찾아 의도를 분류"""

    for keyword in GRADUATION_KEYWORDS:
        if keyword in question:
            return IntentType.GRADUATION

    for keyword in SCHEDULE_KEYWORDS:
        if keyword in question:
            return IntentType.SCHEDULE

    return IntentType.GENERAL
