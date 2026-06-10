import re
from app.agents.intent import IntentType

SPECIAL_CREDIT_KEYWORDS = ["특별학점", "학점인정", "재수강", "비교과", "자격증학점","학점취득", "특별이수", "비교과학점", "학점 인정"]
GRADUATION_KEYWORDS  = ["졸업", "학점", "필수과목", "전공필수", "교양필수", "이수", "졸업요건", "졸업조건", "졸업학점"]
SCHEDULE_KEYWORDS    = ["수강신청", "학사일정", "중간고사", "기말고사", "방학", "개강", "종강", "시험일정", "수업일정"]
LEAVE_KEYWORDS       = ["휴학", "복학", "군휴학", "휴학신청", "휴학절차", "휴학방법", "창업휴학", "육아휴학", "휴학기간"]
CAMPUS_KEYWORDS      = ["건물", "위치", "캠퍼스", "강의실", "학과사무실", "도서관", "체육관", "식당", "호실", "층"]
SCHOLARSHIP_KEYWORDS = ["장학금", "장학", "장학생", "장학신청", "성적장학", "국가장학", "장학금신청", "장학금조건", "장학금지원"]
OT_KEYWORDS          = ["오리엔테이션", "OT","ot", "신입생 OT", "학과 OT", "오티", "OT 안내", "OT 일정","신입생 오리엔테이션","신입생행사","입학행사","솔숲","솔숲 OT","SOL_SUP"]

# 건물 코드 패턴: W(서캠), E(동캠), S(기타) + 숫자 (예: W15, E3, S1)
_BUILDING_CODE_RE = re.compile(r'[WwEeSs]\d{1,2}')


def classify_intent(question: str) -> IntentType:
    for keyword in SPECIAL_CREDIT_KEYWORDS:
        if keyword in question:
            return IntentType.SPECIAL_CREDIT
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
    # 건물 코드 패턴 감지 (W15, E3, S1 등)
    if _BUILDING_CODE_RE.search(question):
        return IntentType.CAMPUS
    for keyword in SCHOLARSHIP_KEYWORDS:
        if keyword in question:
            return IntentType.SCHOLARSHIP
    for keyword in OT_KEYWORDS:
        if keyword in question:
            return IntentType.OT
    return IntentType.GENERAL
