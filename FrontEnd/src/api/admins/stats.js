import { authFetch } from '../utils'

const BASE = 'http://localhost:8000/api/admins'

export async function fetchStats() {
  const res = await authFetch(`${BASE}/stats`)
  if (!res.ok) throw new Error('통계 조회 실패')
  return res.json()
}

export async function fetchDashboard() {
  const res = await authFetch(`${BASE}/dashboard`)
  if (!res.ok) throw new Error('대시보드 조회 실패')
  return res.json()
}
