import { authFetch } from '../utils'

const BASE = 'http://localhost:8000/api/admins'

export async function fetchUsers() {
  const res = await authFetch(`${BASE}/users`)
  if (!res.ok) throw new Error('사용자 목록 조회 실패')
  return res.json()
}

export async function updateUserRole(userId, role) {
  const res = await authFetch(`${BASE}/users/${userId}/role`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  })
  if (!res.ok) throw new Error('권한 변경 실패')
  return res.json()
}
