import re

def detect_language(text: str) -> str:
    """질문 텍스트에서 언어 감지. 'ko', 'en', 'zh' 반환"""
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    korean  = len(re.findall(r'[\uac00-\ud7af]', text))
    if chinese > 0:
        return 'zh'
    if korean > 0:
        return 'ko'
    return 'en'


def pick(lang: str, ko: str, en: str, zh: str) -> str:
    """언어 코드에 맞는 문자열 반환"""
    if lang == 'zh':
        return zh
    if lang == 'en':
        return en
    return ko