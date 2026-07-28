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
