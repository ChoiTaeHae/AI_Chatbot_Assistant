import { authFetch } from './utils'

const BASE = '/api'

/**
 * 카탈로그 조회 ('장학금·근로 둘러보기' 모달).
 * kind: '장학금' | '근로', scope: '교내' | '교외', q: 검색어(옵션)
 * 반환: { kind, scope, count, groups, counts:{교내,교외}, kind_counts:{장학금,근로} }
 * 각 item: { id, name, category, amount, eligibility, period, expired, files, link }
 */
export async function getScholarships(kind = '장학금', scope = '교내', q = '') {
  const params = new URLSearchParams({ kind, scope })
  if (q) params.set('q', q)
  const res = await authFetch(`${BASE}/scholarships?${params.toString()}`, { method: 'GET' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '장학금 정보를 불러오지 못했습니다.')
  }
  return res.json()
}

/**
 * 맞춤 설문 자동 연동 프로필 (설문 모달 상단 표시용).
 * 반환: { name, gpa, grade_year, major_field, dept_name }
 */
/** 설문 '관심 유형' 칩 목록 — DB 실제 카테고리 { categories: [{category, count}] } */
export async function fetchScholarshipCategories() {
  const res = await authFetch(`${BASE}/scholarships/categories`, { method: 'GET' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '장학금 유형을 불러오지 못했습니다.')
  }
  return res.json()
}

export async function fetchMyScholarshipProfile() {
  const res = await authFetch(`${BASE}/scholarships/profile`, { method: 'GET' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '내 정보를 불러오지 못했습니다.')
  }
  return res.json()
}

/**
 * 맞춤 장학금 설문 필터. answers는 설문 답(성적·학년·전공은 서버가 학생 레코드에서 자동 연동).
 * 반환: { count, items:[...], profile:{ name, gpa, grade_year, major_field, dept_name } }
 */
export async function matchScholarships(answers) {
  const res = await authFetch(`${BASE}/scholarships/match`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(answers),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '맞춤 장학금 조회에 실패했습니다.')
  }
  return res.json()
}
