const BASE = 'http://localhost:8000/api/admin'

export async function uploadDocument(file, source = null) {
  const formData = new FormData()
  formData.append('file', file)
  if (source) formData.append('source', source)

  const res = await fetch(`${BASE}/documents/upload`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '업로드에 실패했습니다.')
  }
  return res.json()
}

export async function fetchDocuments() {
  const res = await fetch(`${BASE}/documents`)
  if (!res.ok) throw new Error('문서 목록 조회 실패')
  return res.json()
}

export async function deleteDocument(source) {
  const res = await fetch(`${BASE}/documents/${encodeURIComponent(source)}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '삭제에 실패했습니다.')
  }
  return res.json()
}
