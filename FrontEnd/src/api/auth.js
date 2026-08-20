import { authFetch } from './utils'

const BASE = '/api'

/** FastAPI 오류 본문에서 읽을 수 있는 문장을 뽑는다.
 *
 * detail은 HTTPException이면 문자열, 검증 실패면 [{loc, msg, type}] 배열이다.
 * 그대로 문자열에 넣으면 화면에 "[object Object]"가 찍혀 원인을 알 수 없다. */
function errorText(err) {
  const d = err?.detail
  if (!d) return ''
  if (typeof d === 'string') return d
  if (Array.isArray(d)) {
    return d.map((e) => e?.msg || '').filter(Boolean).join(', ')
  }
  return d?.msg || ''
}

export async function login(student_no, password) {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ student_no, password }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(errorText(err) || '로그인에 실패했습니다.')
  }
  return res.json()
}

/** 회원가입 — 성공하면 로그인과 같은 형태(토큰 포함)를 돌려주므로 바로 saveUser에 넣으면 된다. */
export async function signup({ student_no, password, name, dept_id }) {
  const res = await fetch(`${BASE}/auth/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ student_no, password, name, dept_id }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(errorText(err) || '회원가입에 실패했습니다.')
  }
  return res.json()
}

/** 가입 화면 학과 목록 — 로그인 전에 필요해서 인증 없이 받는다. */
export async function getSignupDepartments() {
  const res = await fetch(`${BASE}/auth/departments`)
  if (!res.ok) throw new Error('학과 목록을 불러오지 못했습니다.')
  return res.json()   // [{ id, name }]
}

export async function logout() {
  const token = sessionStorage.getItem('wsu_token')
  await fetch(`${BASE}/auth/logout`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
}
