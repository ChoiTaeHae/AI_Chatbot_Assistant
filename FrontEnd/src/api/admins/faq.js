import { authFetch } from '../utils'

const BASE = '/api/admins'

async function _json(res, fallback) {
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || fallback)
  return res.json()
}

const JSON_HEAD = { 'Content-Type': 'application/json' }

/** FAQ 목록 (답변 + 매칭용 질문 변형) */
export async function fetchFaqs() {
  return _json(await authFetch(`${BASE}/faqs`), 'FAQ 목록 조회 실패')
}

/** data = { answer, category, questions: string[] } */
export async function createFaq(data) {
  return _json(await authFetch(`${BASE}/faqs`, {
    method: 'POST', headers: JSON_HEAD, body: JSON.stringify(data),
  }), 'FAQ 추가 실패')
}

/** data = { answer?, category?, enabled?, questions? } — questions를 주면 목록 전체를 교체 */
export async function updateFaq(id, data) {
  return _json(await authFetch(`${BASE}/faqs/${id}`, {
    method: 'PATCH', headers: JSON_HEAD, body: JSON.stringify(data),
  }), 'FAQ 수정 실패')
}

export async function deleteFaq(id) {
  return _json(await authFetch(`${BASE}/faqs/${id}`, { method: 'DELETE' }), 'FAQ 삭제 실패')
}

/** 표를 SQL로 직접 고쳤을 때만 필요 — 화면 저장은 서버가 자동으로 재적재한다 */
export async function reloadFaqIndex() {
  return _json(await authFetch(`${BASE}/faq/reload`, { method: 'POST' }), 'FAQ 인덱스 재적재 실패')
}
