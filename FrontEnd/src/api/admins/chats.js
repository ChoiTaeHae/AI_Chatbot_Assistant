import { authFetch } from '../utils'

const BASE = '/api/admins'

export async function fetchChatSessions({ search = '', page = 1, limit = 50 } = {}) {
  const params = new URLSearchParams({ page, limit })
  if (search) params.set('search', search)
  const res = await authFetch(`${BASE}/chat-sessions?${params}`)
  if (!res.ok) throw new Error('채팅 세션 목록 조회 실패')
  return res.json()
}

export async function fetchSessionMessages(sessionId) {
  const res = await authFetch(`${BASE}/chat-sessions/${sessionId}/messages`)
  if (!res.ok) throw new Error('채팅 메시지 조회 실패')
  return res.json()
}

export async function upsertMessageFeedback(sessionId, messageId, { is_helpful, rating, comment }) {
  const res = await authFetch(
    `${BASE}/chat-sessions/${sessionId}/messages/${messageId}/feedback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_helpful, rating: rating || null, comment: comment || null }),
    }
  )
  if (!res.ok) throw new Error('피드백 저장 실패')
  return res.json()
}
