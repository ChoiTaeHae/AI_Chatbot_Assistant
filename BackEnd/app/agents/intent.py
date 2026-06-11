from enum import Enum


class IntentType(str, Enum):
    GRADUATION     = "graduation"
    SCHEDULE       = "schedule"
    LEAVE          = "leave"
    CAMPUS         = "campus"
    SCHOLARSHIP    = "scholarship"
    SPECIAL_CREDIT = "special_credit"
    ABSENCE        = "absence"
    OT             = "ot"
    GENERAL        = "general"