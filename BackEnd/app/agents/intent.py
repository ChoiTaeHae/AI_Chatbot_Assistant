from enum import Enum


class IntentType(str, Enum):

    RAG_GENERAL = "rag_general"

    GRADUATION = "graduation"

    CAMPUS = "campus"

    GENERAL = "general"
