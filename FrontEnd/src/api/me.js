import { authFetch } from './utils'

const BASE = '/api/me'

async function _json(res, fallback) {
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || fallback)
  return res.json()
}

const JSON_HEAD = { 'Content-Type': 'application/json' }

/** 내 정보 — 학번·이름·학과·학년·학점·전공계열·관심목록 */
export async function fetchMe() {
  return _json(await authFetch(BASE), '내 정보를 불러오지 못했어요.')
}

/** 학과 선택 목록 — major_field가 함께 와서 학과를 고르면 계열을 바로 채운다 */
export async function fetchDeptOptions() {
  return _json(await authFetch(`${BASE}/departments`), '학과 목록을 불러오지 못했어요.')
}

/** data = { dept_id?, grade_year?, gpa?, major_field?, interests? } — 준 항목만 바뀐다 */
export async function updateMe(data) {
  return _json(await authFetch(BASE, {
    method: 'PATCH', headers: JSON_HEAD, body: JSON.stringify(data),
  }), '저장하지 못했어요.')
}

export async function changePassword(currentPassword, newPassword) {
  return _json(await authFetch(`${BASE}/password`, {
    method: 'POST',
    headers: JSON_HEAD,
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  }), '비밀번호를 변경하지 못했어요.')
}

// ── 수강 이력 ──────────────────────────────────────────────

/** 저장된 수강 이력 */
export async function fetchCourses() {
  return _json(await authFetch(`${BASE}/courses`), '수강 이력을 불러오지 못했어요.')
}

/** 엑셀 미리보기 — 저장하지 않고 파싱 결과만 받는다.
 *  FormData를 쓸 때 Content-Type을 직접 넣으면 multipart 경계(boundary)가 빠져 서버가
 *  파싱하지 못한다. 브라우저가 알아서 붙이도록 헤더를 지정하지 않는다. */
export async function previewCourses(file) {
  const fd = new FormData()
  fd.append('file', file)
  return _json(await authFetch(`${BASE}/courses/preview`, { method: 'POST', body: fd }),
    '엑셀을 읽지 못했어요.')
}

/** 미리보기 결과를 병합 저장 */
export async function commitCourses(rows) {
  return _json(await authFetch(`${BASE}/courses/commit`, {
    method: 'POST', headers: JSON_HEAD, body: JSON.stringify({ rows }),
  }), '저장하지 못했어요.')
}

/** 수강 과목 직접 추가 */
export async function addCourse(row) {
  return _json(await authFetch(`${BASE}/courses`, {
    method: 'POST', headers: JSON_HEAD, body: JSON.stringify(row),
  }), '과목을 추가하지 못했어요.')
}

export async function deleteCourse(id) {
  return _json(await authFetch(`${BASE}/courses/${id}`, { method: 'DELETE' }),
    '과목을 삭제하지 못했어요.')
}
