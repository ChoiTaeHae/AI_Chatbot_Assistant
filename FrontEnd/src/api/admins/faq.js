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

/* ── 미답변 질문 → FAQ 전환 ─────────────────────────────────────
 * 챗봇이 답하지 못한 질문이 쌓이는 곳. 답변을 저장하면 그대로 FAQ가 되고
 * 서버가 인덱스를 재적재해 다음 학생부터 바로 답을 받는다.
 * status: pending(대기) / answered(전환됨) / ignored(제외) / filtered(자동 걸러짐)
 */
export async function fetchUnanswered(status = 'pending') {
  return _json(
    await authFetch(`${BASE}/faq/unanswered?status=${encodeURIComponent(status)}`),
    '미답변 질문 조회 실패',
  )
}

/** 사이드바 배지용 — { pending: number } */
export async function fetchUnansweredCount() {
  return _json(await authFetch(`${BASE}/faq/unanswered/count`), '미답변 건수 조회 실패')
}

/** 되돌릴 수 없는 삭제. 평소 정리는 setUnansweredStatus(id, 'ignored')를 쓴다 —
 *  제외는 행을 남겨 같은 질문이 다시 올라오지 않게 막지만, 삭제는 처음부터 다시 수집된다. */
export async function deleteUnanswered(id) {
  return _json(await authFetch(`${BASE}/faq/unanswered/${id}`, { method: 'DELETE' }), '삭제 실패')
}

export async function setUnansweredStatus(id, status) {
  return _json(await authFetch(`${BASE}/faq/unanswered/${id}`, {
    method: 'PATCH', headers: JSON_HEAD, body: JSON.stringify({ status }),
  }), '상태 변경 실패')
}

/** answer = 검수 답변, extraQuestions = 질문 변형(표현이 달라도 잡히게 하는 핵심) */
export async function answerUnanswered(id, answer, extraQuestions = []) {
  return _json(await authFetch(`${BASE}/faq/unanswered/${id}/answer`, {
    method: 'POST', headers: JSON_HEAD,
    body: JSON.stringify({ answer, extra_questions: extraQuestions }),
  }), '답변 저장 실패')
}
