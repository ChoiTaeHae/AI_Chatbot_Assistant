import { authFetch } from './utils'

const BASE = '/api'

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

export async function sendMessage(question, session_id = null, pendingFile = null, pendingContext = null, lang = 'ko', file_confirm = null) {
  const res = await authFetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, session_id, pending_file: pendingFile, pending_context: pendingContext, lang, file_confirm }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'AI 응답을 불러오지 못했습니다.')
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
