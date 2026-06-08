const BASE = 'http://localhost:8000/api/admin'

export async function uploadDocument(file, source = null, topic = null) {
  const formData = new FormData()
  formData.append('file', file)
  if (source) formData.append('source', source)
  if (topic) formData.append('topic', topic)

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

export async function pollUploadStatus(jobId, onUpdate) {
  let failCount = 0
  while (true) {
    await new Promise(r => setTimeout(r, 5000)) // 5초마다 확인
    try {
      const res = await fetch(`${BASE}/documents/status/${encodeURIComponent(jobId)}`)
      if (!res.ok) {
        failCount++
        if (failCount >= 5) throw new Error('상태 확인에 반복 실패했습니다.')
        continue
      }
      failCount = 0
      const data = await res.json()
      onUpdate(data)
      if (data.status === 'done' || data.status === 'error') return data
    } catch (e) {
      failCount++
      if (failCount >= 5) throw e
    }
  }
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
