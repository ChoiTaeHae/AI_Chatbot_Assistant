import { authFetch } from '../utils'

const BASE = '/api/admins'

export async function fetchFiles() {
  const res = await authFetch(`${BASE}/files`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '파일 목록 조회 실패')
  }
  return res.json()
}

export async function uploadFile(file, topic, scholarshipId = null, isPrimary = false) {
  const form = new FormData()
  form.append('file', file)
  form.append('topic', topic)
  if (scholarshipId) {
    form.append('scholarship_id', scholarshipId)
    form.append('is_primary', isPrimary ? 'true' : 'false')
  }

  const res = await authFetch(`${BASE}/files/upload`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '파일 업로드 실패')
  }
  return res.json()
}

/** 파일 연결 드롭다운용 장학금 목록 */
export async function fetchScholarshipOptions() {
  const res = await authFetch(`${BASE}/scholarship-catalog`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '장학금 목록 조회 실패')
  }
  return res.json()
}

/** 기존 파일을 장학금에 연결 (scholarshipId=null 이면 연결 해제) */
export async function setScholarshipLink(documentFileId, scholarshipId, isPrimary = false) {
  if (!scholarshipId) {
    const res = await authFetch(`${BASE}/files/link/${documentFileId}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('연결 해제 실패')
    return res.json()
  }
  const res = await authFetch(`${BASE}/files/link`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ document_file_id: documentFileId, scholarship_id: scholarshipId, is_primary: isPrimary }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '연결 실패')
  }
  return res.json()
}

export async function deleteFile(topic, filename) {
  const res = await authFetch(
    `${BASE}/files/${encodeURIComponent(topic)}/${encodeURIComponent(filename)}`,
    { method: 'DELETE' }
  )
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '파일 삭제 실패')
  }
  return res.json()
}

export async function downloadFile(topic, filename) {
  const res = await authFetch(
    `${BASE}/files/${encodeURIComponent(topic)}/${encodeURIComponent(filename)}`
  )
  if (!res.ok) throw new Error('파일 다운로드 실패')

  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
