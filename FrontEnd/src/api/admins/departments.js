import { authFetch } from '../utils'

const BASE = '/api/admins/dept'

async function _json(res, fallback) {
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || fallback)
  return res.json()
}

/** 학과 트리 (단과대학→학부→학과 + 미분류) */
export async function fetchDeptTree() {
  return _json(await authFetch(`${BASE}/tree`), '학과 트리 조회 실패')
}

// ─────────────── 단과대학 ───────────────
export async function createCollege(name) {
  return _json(await authFetch(`${BASE}/college`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
  }), '단과대학 추가 실패')
}
export async function updateCollege(id, name) {
  return _json(await authFetch(`${BASE}/college/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
  }), '단과대학 수정 실패')
}
export async function deleteCollege(id) {
  return _json(await authFetch(`${BASE}/college/${id}`, { method: 'DELETE' }), '단과대학 삭제 실패')
}

// ─────────────── 학부 ───────────────
export async function createDivision(data) {
  return _json(await authFetch(`${BASE}/division`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  }), '학부 추가 실패')
}
export async function updateDivision(id, data) {
  return _json(await authFetch(`${BASE}/division/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  }), '학부 수정 실패')
}
export async function deleteDivision(id) {
  return _json(await authFetch(`${BASE}/division/${id}`, { method: 'DELETE' }), '학부 삭제 실패')
}

// ─────────────── 학과 ───────────────
export async function createDepartment(data) {
  return _json(await authFetch(`${BASE}/department`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  }), '학과 추가 실패')
}
export async function updateDepartment(id, data) {
  return _json(await authFetch(`${BASE}/department/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  }), '학과 수정 실패')
}
export async function deleteDepartment(id) {
  return _json(await authFetch(`${BASE}/department/${id}`, { method: 'DELETE' }), '학과 삭제 실패')
}
