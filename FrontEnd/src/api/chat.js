import { authFetch } from './utils'

const BASE = 'http://localhost:8000/api'

export async function sendMessage(question, session_id = null, pendingFile = null, lang = 'ko') {
  const res = await authFetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, session_id, pending_file: pendingFile, lang }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'AI 응답을 불러오지 못했습니다.')
  }
  return res.json()
}
