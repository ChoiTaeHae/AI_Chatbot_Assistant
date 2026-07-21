import { authFetch } from './utils'

const BASE = 'http://localhost:8000/api'

// 해당 월에 걸치는 일정 (사이드바 달력 점 표시용)
export async function fetchScheduleMonth(year, month, track = '학부') {
  const qs = new URLSearchParams({ year: String(year), month: String(month), track })
  const res = await authFetch(`${BASE}/schedule/month?${qs}`)
  if (!res.ok) throw new Error('학사일정 조회 실패')
  return res.json()
}

// 오늘 기준 진행 중 + 다가오는 일정 (사이드바 하단 고정 목록)
export async function fetchScheduleUpcoming(limit = 3, track = '학부') {
  const qs = new URLSearchParams({ limit: String(limit), track })
  const res = await authFetch(`${BASE}/schedule/upcoming?${qs}`)
  if (!res.ok) throw new Error('다가오는 학사일정 조회 실패')
  return res.json()
}
