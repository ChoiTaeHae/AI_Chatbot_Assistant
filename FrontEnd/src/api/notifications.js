import { authFetch } from './utils'

/* 학생 알림 — 답을 못 받았던 내 질문에 관리자가 답변을 등록하면 여기로 온다.
 * 관리자 쪽 미답변 목록(api/admins/faq.js)과 짝이지만 경로도 권한도 다르다. */

const BASE = '/api'

async function _json(res, fallback) {
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || fallback)
  return res.json()
}

/** 답변이 등록된 내 알림 목록 (최근순) */
export async function fetchNotifications() {
  return _json(await authFetch(`${BASE}/notifications`), '알림 조회 실패')
}

/** 종 빨간 점 판정용 — { unread: number } */
export async function fetchNotificationCount() {
  return _json(await authFetch(`${BASE}/notifications/count`), '알림 개수 조회 실패')
}

export async function markNotificationRead(id) {
  return _json(
    await authFetch(`${BASE}/notifications/${id}/read`, { method: 'POST' }),
    '알림 읽음 처리 실패',
  )
}
