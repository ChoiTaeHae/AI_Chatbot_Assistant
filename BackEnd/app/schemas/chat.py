from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., max_length=2000)
    session_id: int | None = None
    pending_file: dict | None = None     # { topic, filename } 파일 제안에 대한 응답 시 프론트가 전달
    pending_context: dict | None = None  # { type: "scholarship" } 멀티턴 대화 상태
    file_confirm: bool | None = None     # 프론트 예/아니오 버튼: True=예, False=아니오, None=일반 질문
    lang: str | None = None              # 프론트 UI 언어(ko/en/zh). 답변 후처리 번역 대상 판정용

    # ── 게스트(비로그인) 전용 멀티턴 맥락 ──────────────────────────────
    # 로그인 사용자는 chat_message에서 직전 대화를 읽어 맥락을 잇지만, 게스트는 대화를
    # 저장하지 않으므로(개인정보를 남기지 않기 위해) 프론트가 직전 1턴을 실어 보낸다.
    # 로그인 상태에서 오면 무시한다 — DB에 있는 실제 기록이 더 정확하고, 클라이언트가
    # 보낸 값으로 맥락을 덮어쓰게 두면 남의 맥락을 주입할 수 있다.
    #
    # 길이 제한을 두지 않는다. 이건 '있으면 좋은 힌트'라서, 길다는 이유로 422를 던지면
    # 질문 자체가 통째로 실패한다(실측: 답변이 500자를 넘는 순간 채팅이 안 됨).
    # 서버가 어차피 앞 200자만 쓰므로(chat_service.MAX_PREV_LENGTH) 받아서 자른다.
    prev_question: str | None = None
    prev_answer: str | None = None
    prev_topic: str | None = None


class ChatResponse(BaseModel):
    answer: str
    session_id: int | None = None
    message_id: int | None = None       # chat_message.id (피드백 연결용)
    file_offer: dict | None = None      # { topic, files: [str] } AI가 파일 목록을 제안할 때
    file_download: dict | None = None   # { topic, filename, url } 파일을 실제로 전송할 때
    map_card: dict | None = None        # { title, address, place_url, latitude, longitude } 캠퍼스 위치 검색 결과
    schedule_card: dict | None = None   # { today, events: [{event, start_date, end_date}] } 학사일정 미니 달력
    dept_card: dict | None = None       # { kind, title, subtitle, items_label, items, homepage_url } 학과/학부/단과대 안내
    scholarship_card: dict | None = None # { items: [{kind, scope, count}] } 장학·근로 큰 분류 카드 (클릭 시 둘러보기 모달 필터 오픈)
    weather_card: dict | None = None    # { place, emoji, temp, feels_like, temp_min/max, humidity, wind, pm10, pm25, sunrise, sunset, hourly[], tomorrow } 캠퍼스 날씨
    pending_context: dict | None = None # { type: "scholarship" } 멀티턴 대화 상태 유지용
    rewritten_query: str | None = None  # 검색용 재작성 질문 (개발용 rewrite 피드백 패널에서 사용, 변경 없으면 null)
    login_required: bool = False        # 게스트가 개인 데이터 기능을 물었을 때 — 프론트가 로그인 버튼 표시
    topic: str | None = None            # 이 답변이 어느 주제로 처리됐나. 게스트가 다음 턴에 그대로 실어 보내
                                        # 멀티턴 맥락을 잇는다(로그인 사용자는 서버가 DB에서 읽으므로 안 씀).


class FeedbackRequest(BaseModel):
    message_id: int
    is_helpful: bool
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = None


class RewriteFeedbackRequest(BaseModel):
    """개발용 rewrite 피드백 — 파인튜닝 라벨 수집."""
    message_id: int | None = None       # 연결할 (assistant) 메시지 id
    question: str                        # 원본 질문 (입력)
    model_rewrite: str | None = None     # 모델이 뱉은 rewrite
    prev_question: str | None = None     # 맥락모드면 이전 질문
    is_good: bool                        # rewrite가 적절했나
    corrected: str | None = None         # 나쁠 때 교정한 정답 rewrite
