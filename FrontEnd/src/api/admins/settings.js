import { authFetch } from '../utils'

const BASE = '/api/admins'

export async function fetchSettings() {
  const res = await authFetch(`${BASE}/settings`)
  if (!res.ok) throw new Error('설정 조회 실패')
  return res.json()
}
