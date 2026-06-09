from enum import Enum


class IntentType(str, Enum):
    GRADUATION      = "graduation"    # 졸업요건 관련
    SCHEDULE        = "schedule"      # 학사일정 관련
    LEAVE           = "leave"         # 휴학 관련
    CAMPUS          = "campus"        # 건물/위치 관련
    SCHOLARSHIP     = "scholarship"   # 장학금 관련
    GENERAL         = "general"       # 일반 질문
    OT              = "ot"            # 오리엔테이션 관련
    SPECIAL_CREDIT  = "special_credit"  # 특별학점 관련
