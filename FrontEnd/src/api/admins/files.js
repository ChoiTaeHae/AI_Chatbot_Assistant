import { authFetch } from '../utils'

const BASE = 'http://localhost:8000/api/admins'

export async function fetchFiles() {
  const res = await authFetch(`${BASE}/files`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '파일 목록 조회 실패')
  }
  return res.json()
}

export async function uploadFile(file, topic) {
  const form = new FormData()
  form.append('file', file)
  form.append('topic', topic)

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
