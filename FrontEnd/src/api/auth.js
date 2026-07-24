import { authFetch } from './utils'

const BASE = '/api'

export async function login(student_no, password) {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ student_no, password }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '로그인에 실패했습니다.')
  }
  return res.json()
}

export async function logout() {
  const token = sessionStorage.getItem('wsu_token')
  await fetch(`${BASE}/auth/logout`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
}
