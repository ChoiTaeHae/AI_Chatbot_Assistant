import { authFetch } from '../utils'

const BASE = 'http://localhost:8000/api/admins'

// URL 크롤링 → academic_schedule 적재 (백그라운드 없이 즉시 처리, 적재 건수 반환)
export async function crawlSchedule(url, keepRecentYears = 2) {
  const formData = new FormData()
  formData.append('url', url)
  formData.append('keep_recent_years', String(keepRecentYears))
  const res = await authFetch(`${BASE}/schedule/crawl`, { method: 'POST', body: formData })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '학사일정 크롤링에 실패했습니다.')
  }
  return res.json()
}

export async function fetchSchedules(track = null, academicYear = null) {
  const params = new URLSearchParams()
  if (track) params.append('track', track)
  if (academicYear) params.append('academic_year', String(academicYear))
  const qs = params.toString()
  const res = await authFetch(`${BASE}/schedule${qs ? '?' + qs : ''}`)
  if (!res.ok) throw new Error('학사일정 조회 실패')
  return res.json()
}

export async function createSchedule(data) {
  const res = await authFetch(`${BASE}/schedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '학사일정 추가 실패')
  }
  return res.json()
}

export async function updateSchedule(id, data) {
  const res = await authFetch(`${BASE}/schedule/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '학사일정 수정 실패')
  }
  return res.json()
}

export async function deleteSchedule(id) {
  const res = await authFetch(`${BASE}/schedule/${id}`, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '학사일정 삭제 실패')
  }
  return res.json()
}
