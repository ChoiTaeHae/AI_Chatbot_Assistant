import { authFetch } from './utils'

const BASE = '/api'

/** FastAPI 오류 본문에서 사람이 읽을 문장을 뽑는다.
 *
 * detail은 문자열일 때도 있고(HTTPException), 검증 실패면 객체 배열일 때도 있다
 * ([{loc, msg, type}, ...]). 예전엔 그대로 문자열에 넣어 "[object Object]"가 화면에
 * 찍혔다 — 무엇이 잘못됐는지 알 수 없는 메시지라 디버깅이 오래 걸린다. */
function errorText(err) {
  const d = err?.detail
  if (!d) return ''
  if (typeof d === 'string') return d
  if (Array.isArray(d)) {
    return d.map((e) => {
      const field = Array.isArray(e?.loc) ? e.loc[e.loc.length - 1] : null
      return field ? `${field}: ${e?.msg || ''}` : (e?.msg || '')
    }).filter(Boolean).join(', ')
  }
  return d?.msg || ''
}

// 백엔드 준비 확인 — /health 는 FastAPI lifespan(모델 로딩·토픽 워밍업)이 끝난 뒤에야
// 응답하므로, 성공 = "완전히 켜져서 요청을 받을 수 있는 상태". 인증 불필요한 경량 핑.
export async function checkBackendHealth() {
  try {
    const res = await fetch(BASE.replace(/\/api\/?$/, '') + '/health', { cache: 'no-store' })
    return res.ok
  } catch {
    return false
  }
}

/**
 * prev: 게스트(비로그인)일 때만 쓰는 직전 1턴 { question, answer, topic }.
 * 로그인 사용자는 서버가 chat_message에서 직접 읽으므로 보내지 않는다(보내도 서버가 무시한다).
 */
export async function sendMessage(question, session_id = null, pendingFile = null, pendingContext = null, lang = 'ko', file_confirm = null, prev = null) {
  const res = await authFetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question, session_id, pending_file: pendingFile, pending_context: pendingContext, lang, file_confirm,
      // 서버는 앞 200자만 쓴다. 답변 전체를 실어 보내면 요청만 커진다.
      prev_question: prev?.question?.slice(0, 200) ?? null,
      prev_answer: prev?.answer?.slice(0, 200) ?? null,
      prev_topic: prev?.topic ?? null,
    }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(errorText(err) || 'AI 응답을 불러오지 못했습니다.')
  }
  return res.json()
}

export async function getGraduationStatus() {
  const res = await authFetch(`${BASE}/graduation/status`, { method: 'GET' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '졸업 현황을 불러오지 못했습니다.')
  }
  return res.json()  // { answer }
}

export async function getGraduationReport() {
  const res = await authFetch(`${BASE}/graduation/report`, { method: 'GET' })
  if (!res.ok) throw new Error('학점 정보를 불러오지 못했습니다.')
  return res.json()  // { available, reason?, dept_name, total_earned, total_required, remaining, student_no }
}

export async function getTodayDining() {
  const res = await authFetch(`${BASE}/dining/today`, { method: 'GET' })
  if (!res.ok) throw new Error('학식 정보를 불러오지 못했습니다.')
  return res.json()  // { available, restaurant, date, weekday, meals: [{ name, items }] }
}

export async function getWeekDining() {
  const res = await authFetch(`${BASE}/dining/week`, { method: 'GET' })
  if (!res.ok) throw new Error('학식 정보를 불러오지 못했습니다.')
  return res.json()  // { available, restaurants: [{ name, days: [{ date, meals: [{ name, items }] }] }] }
}

export async function getMySessions() {
  const res = await authFetch(`${BASE}/chat/sessions`, { method: 'GET' })
  if (!res.ok) throw new Error('대화 목록을 불러오지 못했습니다.')
  return res.json()  // [{ id, title, topic, last_message_at }]
}

export async function getSessionMessages(sessionId) {
  const res = await authFetch(`${BASE}/chat/sessions/${sessionId}`, { method: 'GET' })
  if (!res.ok) throw new Error('대화를 불러오지 못했습니다.')
  return res.json()  // { session_id, messages: [{ id, role, content, topic, message_id }] }
}

export async function deleteSession(sessionId) {
  const res = await authFetch(`${BASE}/chat/sessions/${sessionId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('대화를 삭제하지 못했습니다.')
  return res.json()  // { ok: true }
}

export async function sendFeedback(message_id, is_helpful, rating = null, comment = null) {
  const res = await authFetch(`${BASE}/chat/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_id, is_helpful, rating, comment }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '피드백 저장에 실패했습니다.')
  }
  return res.json()
}

// [개발용] rewrite 피드백 — 파인튜닝 라벨 수집 (배포 시 호출부와 함께 제거)
export async function sendRewriteFeedback({ message_id, question, model_rewrite, prev_question = null, is_good, corrected = null }) {
  const res = await authFetch(`${BASE}/chat/rewrite-feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_id, question, model_rewrite, prev_question, is_good, corrected }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'rewrite 피드백 저장에 실패했습니다.')
  }
  return res.json()
}
