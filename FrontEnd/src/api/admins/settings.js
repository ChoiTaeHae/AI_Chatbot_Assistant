const BASE = 'http://localhost:8000/api/admins'

export async function fetchSettings() {
  const res = await fetch(`${BASE}/settings`)
  if (!res.ok) throw new Error('설정 조회 실패')
  return res.json()
}
