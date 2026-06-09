const BASE = 'http://localhost:8000/api/admins'

/** 전체 파일 목록 조회 (topic별 그룹) */
export async function fetchFiles() {
  const res = await fetch(`${BASE}/files`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '파일 목록 조회 실패')
  }
  return res.json()   // { files: { graduation: [...], ... }, labels: {...} }
}

/** 파일 업로드 (디스크 저장만, RAG 미사용) */
export async function uploadFile(file, topic) {
  const form = new FormData()
  form.append('file', file)
  form.append('topic', topic)

  const res = await fetch(`${BASE}/files/upload`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '파일 업로드 실패')
  }
  return res.json()
}

/** 파일 삭제 */
export async function deleteFile(topic, filename) {
  const res = await fetch(
    `${BASE}/files/${encodeURIComponent(topic)}/${encodeURIComponent(filename)}`,
    { method: 'DELETE' }
  )
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '파일 삭제 실패')
  }
  return res.json()
}

/** 파일 다운로드 (Blob → 브라우저 다운로드) */
export async function downloadFile(topic, filename) {
  const res = await fetch(
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
