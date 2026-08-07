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

/** 카테고리 표시 순서 조회 — { categories: string[] } */
export async function fetchCategoryOrder() {
  const res = await authFetch(`${BASE}/scholarships/category-order`)
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '카테고리 순서 조회 실패')
  return res.json()
}

/** 카테고리 표시 순서 저장 (둘러보기·관리 목록 공통) */
export async function saveCategoryOrder(categories) {
  const res = await authFetch(`${BASE}/scholarships/category-order`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ categories }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '카테고리 순서 저장 실패')
  return res.json()
}

/** 한 카테고리 안 장학금 표시 순서 저장 — ids는 표시할 순서대로 */
export async function saveScholarshipOrder(ids) {
  const res = await authFetch(`${BASE}/scholarships/order`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '장학금 순서 저장 실패')
  return res.json()
}

/** 학과 목록 (지원 요건 '대상 학과' 다중선택용) — string[] */
export async function fetchDepartments() {
  const res = await authFetch(`${BASE}/departments`)
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || '학과 목록 조회 실패')
  return res.json()
}
