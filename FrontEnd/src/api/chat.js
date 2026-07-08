import { authFetch } from './utils'

const BASE = 'http://localhost:8000/api'

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
