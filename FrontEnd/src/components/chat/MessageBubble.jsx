import { useState } from 'react'
import MascotAvatar from '../common/MascotAvatar'
import { sendFeedback } from '../../api/chat'

const API_BASE = 'http://localhost:8000'

/**
 * 인증 헤더를 포함해서 파일을 fetch한 뒤 blob URL로 다운로드.
 * <a href> 직접 연결 시 Authorization 헤더가 전송되지 않으므로 이 방식 사용.
 */
async function downloadFileWithAuth(url, filename) {
  const token = sessionStorage.getItem('wsu_token')
  try {
    const res = await fetch(`${API_BASE}${url}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) throw new Error('서버 응답 오류')
    const blob = await res.blob()
    const objectUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(objectUrl)
  } catch {
    alert('파일 다운로드에 실패했습니다.')
  }
}

// ── [DEV-ONLY] 피드백 상세 입력 모달 ──────────────────────────────────────────
function FeedbackModal({ type, onSubmit, onClose }) {
  const [rating, setRating] = useState(null)
  const [hoverRating, setHoverRating] = useState(null)
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setSubmitting(true)
    await onSubmit(type === 'like', rating, comment.trim() || null)
    setSubmitting(false)
  }

  const isLike = type === 'like'
  const accentColor = isLike ? '#005956' : '#e53e3e'

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.35)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#fff', borderRadius: '16px', padding: '24px 28px',
          width: '340px', boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
          position: 'relative',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* 상단 라벨 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
          <span style={{ fontSize: '20px' }}>{isLike ? '👍' : '👎'}</span>
          <span style={{ fontWeight: 700, fontSize: '15px', color: accentColor }}>
            {isLike ? '도움이 됐나요?' : '어떤 점이 아쉬웠나요?'}
          </span>
          <span
            style={{
              marginLeft: 'auto', fontSize: '10px', fontWeight: 600,
              background: '#fef3c7', color: '#92400e',
              padding: '2px 7px', borderRadius: '999px', letterSpacing: '0.05em',
            }}
          >
            DEV ONLY
          </span>
        </div>

        <form onSubmit={handleSubmit}>
          {/* 별점 */}
          <div style={{ marginBottom: '14px' }}>
            <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '6px' }}>
              평점 <span style={{ color: '#94a3b8' }}>(선택)</span>
            </div>
            <div style={{ display: 'flex', gap: '6px' }}>
              {[1, 2, 3, 4, 5].map(n => (
                <button
                  key={n}
                  type="button"
                  onMouseEnter={() => setHoverRating(n)}
                  onMouseLeave={() => setHoverRating(null)}
                  onClick={() => setRating(rating === n ? null : n)}
                  style={{
                    fontSize: '24px', background: 'none', border: 'none',
                    cursor: 'pointer', padding: '0',
                    color: n <= (hoverRating ?? rating ?? 0) ? '#f59e0b' : '#d1d5db',
                    transition: 'color 0.1s',
                  }}
                >
                  ★
                </button>
              ))}
              {rating && (
                <span style={{ fontSize: '12px', color: '#64748b', alignSelf: 'center', marginLeft: '4px' }}>
                  {rating}점
                </span>
              )}
            </div>
          </div>

          {/* 코멘트 */}
          <div style={{ marginBottom: '18px' }}>
            <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '6px' }}>
              의견 <span style={{ color: '#94a3b8' }}>(선택)</span>
            </div>
            <textarea
              value={comment}
              onChange={e => setComment(e.target.value)}
              placeholder="자유롭게 입력해 주세요"
              rows={3}
              style={{
                width: '100%', resize: 'none', padding: '10px 12px',
                borderRadius: '10px', border: '1px solid #e2e8f0',
                fontSize: '13px', outline: 'none', boxSizing: 'border-box',
                fontFamily: 'inherit', color: '#334155',
              }}
            />
          </div>

          {/* 버튼 */}
          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                padding: '8px 16px', borderRadius: '8px', border: '1px solid #e2e8f0',
                background: '#f8fafc', color: '#64748b', fontSize: '13px',
                cursor: 'pointer', fontWeight: 500,
              }}
            >
              취소
            </button>
            <button
              type="submit"
              disabled={submitting}
              style={{
                padding: '8px 18px', borderRadius: '8px', border: 'none',
                background: accentColor, color: '#fff', fontSize: '13px',
                cursor: submitting ? 'not-allowed' : 'pointer', fontWeight: 600,
                opacity: submitting ? 0.7 : 1,
              }}
            >
              {submitting ? '저장 중...' : '저장'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
// ── [DEV-ONLY] ────────────────────────────────────────────────────────────────

function MessageActions({ messageId, content }) {
  const [feedback, setFeedback] = useState(null) // null | 'like' | 'dislike'
  const [modalType, setModalType] = useState(null) // null | 'like' | 'dislike'
  const [copied, setCopied] = useState(false)

  function handleFeedbackClick(type) {
    if (!messageId) return
    if (feedback === type) {
      // 이미 선택된 버튼 재클릭 → UI만 취소 (DB는 마지막 저장값 유지)
      setFeedback(null)
      return
    }
    setModalType(type)
  }

  async function handleModalSubmit(isHelpful, rating, comment) {
    const type = isHelpful ? 'like' : 'dislike'
    try {
      await sendFeedback(messageId, isHelpful, rating, comment)
      setFeedback(type)
    } catch {
      // 실패 시 아무것도 안 함
    }
    setModalType(null)
  }

  function handleCopy() {
    navigator.clipboard.writeText(content).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <>
      {modalType && (
        <FeedbackModal
          type={modalType}
          onSubmit={handleModalSubmit}
          onClose={() => setModalType(null)}
        />
      )}
      <div className="flex items-center gap-3 text-slate-400" style={{ marginTop: '12px' }}>
        {/* 복사 */}
        <button type="button" onClick={handleCopy} className="hover:text-slate-600 transition" title="복사">
          {copied ? (
            <svg className="h-5 w-5 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          ) : (
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
          )}
        </button>
        {/* 좋아요 */}
        <button
          type="button"
          onClick={() => handleFeedbackClick('like')}
          className="transition"
          style={{ color: feedback === 'like' ? '#005956' : undefined }}
          title="좋아요"
        >
          <svg className="h-5 w-5" fill={feedback === 'like' ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6.633 10.25c.806 0 1.533-.446 2.031-1.08a9.041 9.041 0 0 1 2.861-2.4c.723-.384 1.35-.956 1.653-1.715a4.498 4.498 0 0 0 .322-1.672V2.75a.75.75 0 0 1 .75-.75 2.25 2.25 0 0 1 2.25 2.25c0 1.152-.26 2.243-.723 3.218-.266.558.107 1.282.725 1.282m0 0h3.126c1.026 0 1.945.694 2.054 1.715.045.422.068.85.068 1.285a11.95 11.95 0 0 1-2.649 7.521c-.388.482-.987.729-1.605.729H13.48c-.483 0-.964-.078-1.423-.23l-3.114-1.04a4.501 4.501 0 0 0-1.423-.23H5.904m10.598-9.75H14.25M5.904 18.5c.083.205.173.405.27.602.197.4-.078.898-.523.898h-.908c-.889 0-1.713-.518-1.972-1.368a12 12 0 0 1-.521-3.507c0-1.553.295-3.036.831-4.398C3.387 9.953 4.167 9.5 5 9.5h1.053c.472 0 .745.556.5.96a8.958 8.958 0 0 0-1.302 4.665c0 1.194.232 2.333.654 3.375Z" />
          </svg>
        </button>
        {/* 싫어요 */}
        <button
          type="button"
          onClick={() => handleFeedbackClick('dislike')}
          className="transition"
          style={{ color: feedback === 'dislike' ? '#e53e3e' : undefined }}
          title="싫어요"
        >
          <svg className="h-5 w-5" fill={feedback === 'dislike' ? 'currentColor' : 'none'} viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M7.498 15.25H4.372c-1.026 0-1.945-.694-2.054-1.715a12.137 12.137 0 0 1-.068-1.285c0-2.848.992-5.464 2.649-7.521C5.287 4.247 5.886 4 6.504 4h4.016a4.5 4.5 0 0 1 1.423.23l3.114 1.04a4.5 4.5 0 0 0 1.423.23h1.294M7.498 15.25c.618 0 .991.724.725 1.282A7.471 7.471 0 0 0 7.5 19.75 2.25 2.25 0 0 0 9.75 22a.75.75 0 0 0 .75-.75v-.633c0-.573.11-1.14.322-1.672.304-.76.93-1.33 1.653-1.715a9.04 9.04 0 0 0 2.86-2.4c.498-.634 1.226-1.08 2.032-1.08h.384m-10.253 1.5H9.7m8.075-9.75c.01.05.027.1.05.148.593 1.2.925 2.55.925 3.977 0 1.487-.36 2.89-.999 4.125m.023-8.25c-.076-.365.183-.75.575-.75h.908c.889 0 1.713.518 1.972 1.368.339 1.11.521 2.287.521 3.507 0 1.553-.295 3.036-.831 4.398-.306.774-1.086 1.227-1.918 1.227h-1.053c-.472 0-.745-.556-.5-.96a8.95 8.95 0 0 0 .303-.54" />
          </svg>
        </button>
      </div>
    </>
  )
}

export default function MessageBubble({ message }) {
  const isUser = message.role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end items-start gap-3" style={{ marginBottom: '15px', paddingRight: '8px' }}>
        <div className="flex flex-col items-end gap-1">
          <div
            className="rounded-2xl rounded-tr-sm bg-[#eaf2f2] text-slate-800 whitespace-pre-wrap break-words"
            style={{ padding: '12px 16px', fontSize: '15px', lineHeight: '1.6', maxWidth: '320px' }}
          >
            {message.content}
          </div>
          <span className="text-xs text-slate-400" style={{ marginTop: '4px' }}>{message.time}</span>
        </div>
        <div className="h-9 w-9 rounded-full bg-slate-100 flex items-center justify-center shrink-0 border border-slate-200" style={{ marginTop: '4px' }}>
          <svg className="h-5 w-5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
          </svg>
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-start gap-4" style={{ marginBottom: '24px', paddingLeft: '8px' }}>
      <MascotAvatar className="h-12 w-12 shrink-0 object-contain" style={{ marginTop: '4px' }} />
      <div style={{ flex: 1, maxWidth: '80%' }}>
        <div
          className="rounded-2xl rounded-tl-sm border border-slate-200 bg-white text-slate-800 shadow-sm"
          style={{ padding: '16px 20px', fontSize: '15px', lineHeight: '1.7' }}
        >
          <div className="whitespace-pre-wrap break-words">
            {message.content.split(/(https?:\/\/[^\s]+)/g).map((part, i) =>
              /^https?:\/\//.test(part) ? (
                <a key={i} href={part} target="_blank" rel="noopener noreferrer" className="text-[#005956] underline underline-offset-2 hover:text-[#004a47] transition">{part}</a>
              ) : part
            )}
          </div>

          {/* 캠퍼스 지도 카드 */}
          {message.mapCard && (
            <div
              className="rounded-xl border border-[#005956]/20 overflow-hidden"
              style={{ marginTop: '14px' }}
            >
              {/* 건물 정보 헤더 */}
              <div className="flex items-center gap-2 bg-[#f0f9f8]" style={{ padding: '10px 14px' }}>
                <div className="shrink-0 rounded-lg bg-[#005956] flex items-center justify-center" style={{ width: '32px', height: '32px' }}>
                  <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z" />
                  </svg>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-[#005956] truncate">{message.mapCard.title}</p>
                  <p className="text-xs text-slate-500 truncate">{message.mapCard.address}</p>
                </div>
              </div>

              {/* 지도 (좌표 있을 때 — OpenStreetMap 무료 임베드) */}
              {message.mapCard.latitude && message.mapCard.longitude ? (
                <div style={{ width: '100%', height: '200px', overflow: 'hidden' }}>
                  <iframe
                    title={message.mapCard.title}
                    src={`https://www.openstreetmap.org/export/embed.html?bbox=${message.mapCard.longitude - 0.003},${message.mapCard.latitude - 0.003},${message.mapCard.longitude + 0.003},${message.mapCard.latitude + 0.003}&layer=mapnik&marker=${message.mapCard.latitude},${message.mapCard.longitude}`}
                    style={{ width: '100%', height: '260px', border: 'none', display: 'block' }}
                  />
                </div>
              ) : null}

              {/* 카카오맵 링크 */}
              {message.mapCard.place_url && (
                <a
                  href={message.mapCard.place_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-center gap-1.5 text-xs font-medium text-[#005956] hover:bg-[#e4f4f3] transition bg-white"
                  style={{ padding: '8px', textDecoration: 'none' }}
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                  </svg>
                  카카오맵에서 크게 보기
                </a>
              )}
            </div>
          )}

          {/* 파일 다운로드 링크 */}
          {message.fileDownload && (
            <div
              className="flex items-center gap-2 rounded-lg border border-blue-100 bg-blue-50"
              style={{ marginTop: '14px', padding: '10px 14px' }}
            >
              <svg className="h-5 w-5 text-blue-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01-.01.01m5.699-9.941-7.81 7.81a1.5 1.5 0 002.112 2.13" />
              </svg>
              <button
                type="button"
                onClick={() =>
                  downloadFileWithAuth(message.fileDownload.url, message.fileDownload.filename)
                }
                className="text-blue-600 underline underline-offset-2 hover:text-blue-800 transition text-sm font-medium truncate"
              >
                {message.fileDownload.filename}
              </button>
            </div>
          )}

          <div className="flex justify-between items-end" style={{ marginTop: '12px' }}>
            <span className="text-xs text-slate-400">{message.time}</span>
            <MessageActions messageId={message.messageId} content={message.content} />
          </div>
        </div>
      </div>
    </div>
  )
}
