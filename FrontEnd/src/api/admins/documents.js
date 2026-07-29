import { authFetch } from '../utils'

const BASE = '/api/admins'

export async function uploadDocument(file, source = null, topic = null, docDate = null, url = null, contactName = null, contactPhone = null) {
  const formData = new FormData()
  formData.append('file', file)
  if (source) formData.append('source', source)
  if (topic) formData.append('topic', topic)
  if (docDate) formData.append('doc_date', docDate)
  if (url) formData.append('url', url)
  if (contactName) formData.append('contact_name', contactName)
  if (contactPhone) formData.append('contact_phone', contactPhone)

  const res = await authFetch(`${BASE}/documents/upload`, {
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
    await new Promise(r => setTimeout(r, 5000))
    try {
      const res = await authFetch(`${BASE}/documents/status/${encodeURIComponent(jobId)}`)
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
  const res = await authFetch(`${BASE}/documents`)
  if (!res.ok) throw new Error('문서 목록 조회 실패')
  return res.json()
}

export async function crawlDocument(url, source = null, topic = null, docDate = null, contactName = null, contactPhone = null) {
  const formData = new FormData()
  formData.append('url', url)
  if (source) formData.append('source', source)
  if (topic) formData.append('topic', topic)
  if (docDate) formData.append('doc_date', docDate)
  if (contactName) formData.append('contact_name', contactName)
  if (contactPhone) formData.append('contact_phone', contactPhone)

  const res = await authFetch(`${BASE}/documents/crawl`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '크롤링 요청에 실패했습니다.')
  }
  return res.json()
}

export async function fetchTopics() {
  const res = await authFetch(`${BASE}/topics`)
  if (!res.ok) throw new Error('토픽 목록 조회 실패')
  const list = await res.json()
  // {name: label} 형태로 변환 (기존 드롭다운 호환)
  return Object.fromEntries(list.map(t => [t.name, t.label]))
}

export async function fetchTopicList() {
  const res = await authFetch(`${BASE}/topics`)
  if (!res.ok) throw new Error('토픽 목록 조회 실패')
  return res.json()
}

export async function createTopic(data) {
  const res = await authFetch(`${BASE}/topics`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '토픽 생성 실패')
  }
  return res.json()
}

export async function updateTopic(name, data) {
  const res = await authFetch(`${BASE}/topics/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '토픽 수정 실패')
  }
  return res.json()
}

export async function deleteTopic(name) {
  const res = await authFetch(`${BASE}/topics/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '토픽 삭제 실패')
  }
  return res.json()
}

// 문서 메타데이터 수정 — 본문·임베딩은 그대로 두고 payload만 갱신하므로 재인제스트가 없다.
// data에 담은 키만 반영된다(빈 문자열은 '값 비우기'로 처리).
export async function updateDocument(source, data) {
  const res = await authFetch(`${BASE}/documents/${encodeURIComponent(source)}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '문서 수정에 실패했습니다.')
  }
  return res.json()
}

// 문서가 실제로 어떻게 쪼개져 저장됐는지 조회 (본문 포함, 벡터는 안 내려온다)
export async function fetchChunks(source) {
  const res = await authFetch(`${BASE}/documents/${encodeURIComponent(source)}/chunks`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '청크 조회에 실패했습니다.')
  }
  return res.json()
}

// 청크 본문 수정 — 서버가 이 청크만 다시 임베딩하므로 응답까지 수 초 걸릴 수 있다.
// 다른 청크는 그대로라 문서 재업로드처럼 전체가 다시 쪼개지지 않는다.
export async function updateChunk(source, chunkIndex, text) {
  const res = await authFetch(
    `${BASE}/documents/${encodeURIComponent(source)}/chunks/${chunkIndex}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    },
  )
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '청크 수정에 실패했습니다.')
  }
  return res.json()
}

export async function deleteDocument(source) {
  const res = await authFetch(`${BASE}/documents/${encodeURIComponent(source)}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '삭제에 실패했습니다.')
  }
  return res.json()
}
