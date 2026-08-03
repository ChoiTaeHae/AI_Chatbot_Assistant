import { authFetch } from '../utils'

const BASE = '/api/admins'

/** 장학금 전체 목록 (관리) — 각 항목에 files:[{topic,name,is_primary}] 포함 */
export async function fetchScholarships() {
  const res = await authFetch(`${BASE}/scholarships`)
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '장학금 목록 조회 실패')
  return res.json()
}

export async function createScholarship(data) {
  const res = await authFetch(`${BASE}/scholarships`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '장학금 추가 실패')
  return res.json()
}

export async function updateScholarship(id, data) {
  const res = await authFetch(`${BASE}/scholarships/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '장학금 수정 실패')
  return res.json()
}

export async function deleteScholarship(id) {
  const res = await authFetch(`${BASE}/scholarships/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '장학금 삭제 실패')
  return res.json()
}

/** 학과 목록 (지원 요건 '대상 학과' 다중선택용) — string[] */
export async function fetchDepartments() {
  const res = await authFetch(`${BASE}/departments`)
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '학과 목록 조회 실패')
  return res.json()
}
