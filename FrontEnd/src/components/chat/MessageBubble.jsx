import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import MascotAvatar from '../common/MascotAvatar'
import ScheduleCard from './ScheduleCard'
import { sendFeedback, sendRewriteFeedback } from '../../api/chat'

const API_BASE = ''

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
  const accentColor = isLike ? 'var(--brand)' : '#e53e3e'

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
          background: 'var(--surface-card)', borderRadius: '16px', padding: '24px 28px',
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
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>
              평점 <span style={{ color: 'var(--text-faint)' }}>(선택)</span>
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
                <span style={{ fontSize: '12px', color: 'var(--text-muted)', alignSelf: 'center', marginLeft: '4px' }}>
                  {rating}점
                </span>
              )}
            </div>
          </div>

          {/* 코멘트 */}
          <div style={{ marginBottom: '18px' }}>
            <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>
              의견 <span style={{ color: 'var(--text-faint)' }}>(선택)</span>
            </div>
            <textarea
              value={comment}
              onChange={e => setComment(e.target.value)}
              placeholder="자유롭게 입력해 주세요"
              rows={3}
              style={{
                width: '100%', resize: 'none', padding: '10px 12px',
                borderRadius: '10px', border: '1px solid var(--border)',
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
                padding: '8px 16px', borderRadius: '8px', border: '1px solid var(--border)',
                background: 'var(--surface-2)', color: 'var(--text-muted)', fontSize: '13px',
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

// ── [DEV-ONLY] rewrite 피드백 패널 (파인튜닝 라벨 수집) ─────────────────────────
// 배포 시: 아래 컴포넌트 + isUser 렌더부(import.meta.env.DEV 블록)만 제거하면 됨.
function RewriteFeedbackPanel({ question, rewrite, messageId }) {
  const [saved, setSaved] = useState(null)      // null | true(좋음) | false(교정)
  const [editing, setEditing] = useState(false)
  const [corrected, setCorrected] = useState(rewrite)
  const [busy, setBusy] = useState(false)

  async function save(isGood, correctedText) {
    setBusy(true)
    try {
      await sendRewriteFeedback({
        message_id: messageId, question, model_rewrite: rewrite,
        is_good: isGood, corrected: correctedText ?? null,
      })
      setSaved(isGood)
      setEditing(false)
    } catch { /* noop */ }
    setBusy(false)
  }

  const btn = (bg, bd, col) => ({
    padding: '4px 10px', borderRadius: '6px', border: `1px solid ${bd}`,
    background: bg, color: col, fontWeight: 600, cursor: busy ? 'default' : 'pointer',
  })

  return (
    <div style={{
      marginTop: '6px', maxWidth: '320px', width: '100%',
      border: '1px dashed var(--border-strong)', borderRadius: '10px',
      background: 'var(--surface-2)', padding: '8px 10px', fontSize: '12px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '5px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '10px', fontWeight: 700, background: '#fef3c7', color: '#92400e', padding: '1px 6px', borderRadius: '999px' }}>DEV</span>
        <span style={{ color: 'var(--text-muted)' }}>재작성:</span>
        <span style={{ color: 'var(--text)', fontWeight: 600 }}>{rewrite}</span>
      </div>
      {saved !== null ? (
        <div style={{ color: saved ? '#059669' : '#e53e3e', fontWeight: 600 }}>
          {saved ? '👍 좋음 저장됨' : '👎 교정 저장됨'}
        </div>
      ) : editing ? (
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
          <input
            value={corrected}
            onChange={e => setCorrected(e.target.value)}
            placeholder="정답 rewrite 입력"
            style={{ flex: 1, padding: '5px 8px', borderRadius: '6px', border: '1px solid var(--border)', fontSize: '12px', outline: 'none' }}
          />
          <button type="button" disabled={busy} onClick={() => save(false, corrected.trim())} style={btn('#e53e3e', '#e53e3e', '#fff')}>저장</button>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: '6px' }}>
          <button type="button" disabled={busy} onClick={() => save(true, null)} style={btn('var(--brand-tint)', 'var(--brand)', 'var(--brand)')}>👍 좋음</button>
          <button type="button" disabled={busy} onClick={() => setEditing(true)} style={btn('#fff5f5', '#e53e3e', '#e53e3e')}>👎 교정</button>
        </div>
      )}
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
      <div className="flex items-center gap-3 text-(--text-faint)" style={{ marginTop: '12px' }}>
        {/* 복사 */}
        <button type="button" onClick={handleCopy} className="hover:text-(--text-muted) transition" title="복사">
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
          style={{ color: feedback === 'like' ? 'var(--brand)' : undefined }}
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

// 카드 정적 라벨 다국어 (동적 데이터(건물명·학과명 등)는 백엔드 값 그대로 — 프론트는 '틀'만 번역).
const CT = {
  ko: { viewMap: '카카오맵에서 크게 보기', mapAria: '위치 지도', deptHome: '학과 홈페이지 바로가기',
        yes: '예', no: '아니요', pickFile: '원하시는 파일을 선택해 주세요.', downloadAll: '전부 다운로드', allDone: '모두 다운로드 완료 ✓' },
  en: { viewMap: 'View on Kakao Map', mapAria: 'location map', deptHome: 'Department homepage',
        yes: 'Yes', no: 'No', pickFile: 'Please select a file.', downloadAll: 'Download all', allDone: 'All downloaded ✓' },
  zh: { viewMap: '在Kakao地图查看', mapAria: '位置地图', deptHome: '前往学科主页',
        yes: '是', no: '否', pickFile: '请选择所需文件。', downloadAll: '全部下载', allDone: '全部下载完成 ✓' },
}

export default function MessageBubble({ message, lang = 'ko', onClearPendingFile, pendingFile, onConfirmFile, isLatest }) {
  const ct = CT[lang] || CT.ko
  const isUser = message.role === 'user'
  const [downloadedFiles, setDownloadedFiles] = useState(new Set())

  if (isUser) {
    return (
      <div className="flex justify-end items-start gap-3" style={{ marginBottom: '15px', paddingRight: '8px' }}>
        <div className="flex flex-col items-end gap-1">
          <div
            className="rounded-2xl rounded-tr-sm bg-(--user-bubble) text-(--text) whitespace-pre-wrap break-words"
            style={{ padding: '12px 16px', fontSize: '15px', lineHeight: '1.6', maxWidth: '320px' }}
          >
            {message.content}
          </div>
          <span className="text-xs text-(--text-faint)" style={{ marginTop: '4px' }}>{message.time}</span>
          {/* [DEV-ONLY] rewrite 피드백 패널 — 배포 시 이 블록 제거 */}
          {import.meta.env.DEV && message.rewrittenQuery && (
            <RewriteFeedbackPanel
              question={message.content}
              rewrite={message.rewrittenQuery}
              messageId={message.rewriteMessageId}
            />
          )}
        </div>
        <div className="h-9 w-9 rounded-full bg-(--surface-2) flex items-center justify-center shrink-0 border border-(--border)" style={{ marginTop: '4px' }}>
          <svg className="h-5 w-5 text-(--text-faint)" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
          className="rounded-2xl rounded-tl-sm border border-(--border) bg-(--surface-card) text-(--text) shadow-sm"
          style={{ padding: '16px 20px', fontSize: '15px', lineHeight: '1.7' }}
        >
          <ReactMarkdown
            className="prose prose-slate max-w-none text-(--text)"
            components={{
              a: ({ href, children }) => (
                <a href={href} target="_blank" rel="noopener noreferrer"
                  className="text-(--brand) underline underline-offset-2 hover:text-(--brand-hover) transition">
                  {children}
                </a>
              ),
              ul: ({ children }) => (
                <ul style={{ listStyleType: 'disc', paddingLeft: '1.25rem', margin: '8px 0' }}>
                  {children}
                </ul>
              ),
              ol: ({ children }) => (
                <ol style={{ listStyleType: 'decimal', paddingLeft: '1.25rem', margin: '8px 0' }}>
                  {children}
                </ol>
              ),
              li: ({ children }) => {
                const first = Array.isArray(children) ? children[0] : children
                const text = typeof first === 'string' ? first : ''
                const hasCircleNum = /^[①-⑳①-⑳]/.test(text.trim())
                return (
                  <li style={{
                    marginBottom: '6px',
                    lineHeight: '1.6',
                    color: 'var(--text)',
                    ...(hasCircleNum ? { listStyleType: 'none', marginLeft: '-1rem' } : {}),
                  }}>
                    {children}
                  </li>
                )
              },
              p: ({ children }) => (
                <p style={{ margin: '6px 0', lineHeight: '1.6' }}>{children}</p>
              ),
              strong: ({ children }) => (
                <strong style={{ fontWeight: 600, color: 'var(--text)' }}>{children}</strong>
              ),
            }}
          >
            {message.content}
          </ReactMarkdown>

          {/* 캠퍼스 지도 카드 */}
          {message.mapCard && (
            <div
              className="rounded-xl border border-(--brand-a20) overflow-hidden"
              style={{ marginTop: '14px' }}
            >
              {/* 건물 정보 헤더 */}
              <div className="flex items-center gap-2 bg-(--brand-tint)" style={{ padding: '10px 14px' }}>
                <div className="shrink-0 rounded-lg bg-(--brand) flex items-center justify-center" style={{ width: '32px', height: '32px' }}>
                  <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 11-6 0 3 3 0 016 0z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1115 0z" />
                  </svg>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-(--brand) truncate">{message.mapCard.title}</p>
                  <p className="text-xs text-(--text-muted) truncate">{message.mapCard.address}</p>
                </div>
              </div>

              {/* 지도 (좌표 있을 때 — OpenStreetMap 무료 임베드).
                  API 키·SDK 로드가 필요 없어 좌표만 있으면 바로 표시된다.
                  bbox는 좌표 주변을 좁게 잡아 건물이 크게 보이도록 한 것. */}
              {message.mapCard.latitude && message.mapCard.longitude && (() => {
                const lat = Number(message.mapCard.latitude)
                const lng = Number(message.mapCard.longitude)
                const dLat = 0.0016, dLng = 0.0022
                const bbox = [lng - dLng, lat - dLat, lng + dLng, lat + dLat].join('%2C')
                return (
                  <>
                    {/* iframe을 컨테이너보다 크게 잡아 OSM 기본 푸터(문제점 보고·기부 링크 등)를
                        아래로 밀어 잘라낸다. 출처 표기는 ODbL 의무라 아래에 한 줄로 대체 표시. */}
                    <div className="relative overflow-hidden bg-(--surface-2)" style={{ height: '190px' }}>
                      <iframe
                        title={`${message.mapCard.title} ${ct.mapAria}`}
                        src={`https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat}%2C${lng}`}
                        loading="lazy"
                        className="absolute top-0 left-0 w-full"
                        style={{ height: '226px', border: 0 }}
                      />
                    </div>
                    <p className="text-(--text-faint) bg-(--surface-card) text-right" style={{ fontSize: '9px', padding: '2px 8px 0' }}>
                      © OpenStreetMap
                    </p>
                  </>
                )
              })()}

              {/* 카카오맵 링크 */}
              {message.mapCard.place_url && (
                <a
                  href={message.mapCard.place_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-center gap-1.5 text-xs font-medium text-(--brand) hover:bg-(--brand-tint) transition bg-(--surface-card)"
                  style={{ padding: '8px', textDecoration: 'none' }}
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                  </svg>
                  {ct.viewMap}
                </a>
              )}
            </div>
          )}


          {/* 학사일정 미니 달력 카드 (일정이 걸친 주만) */}
          {message.scheduleCard && <ScheduleCard card={message.scheduleCard} lang={lang} />}

          {/* 학과/학부/단과대 안내 카드 — 소개 본문은 담지 않고 소속 정보 + 홈페이지 링크만 */}
          {message.deptCard && (
            <div
              className="rounded-xl border border-(--brand-a20) overflow-hidden"
              style={{ marginTop: '14px' }}
            >
              <div className="flex items-center gap-2 bg-(--brand-tint)" style={{ padding: '10px 14px' }}>
                <div className="shrink-0 rounded-lg bg-(--brand) flex items-center justify-center" style={{ width: '32px', height: '32px' }}>
                  <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.26 10.147a60.436 60.436 0 00-.491 6.347A48.627 48.627 0 0112 20.904a48.627 48.627 0 018.232-4.41 60.46 60.46 0 00-.491-6.347m-15.482 0a50.57 50.57 0 00-2.658-.813A59.905 59.905 0 0112 3.493a59.902 59.902 0 0110.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.697 50.697 0 0112 13.489a50.702 50.702 0 017.74-3.342" />
                  </svg>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-(--brand) truncate">{message.deptCard.title}</p>
                  <p className="text-xs text-(--text-muted) truncate">{message.deptCard.subtitle}</p>
                </div>
              </div>

              {/* 형제 학과 / 소속 학과 목록 */}
              {message.deptCard.items?.length > 0 && (
                <div className="bg-(--surface-card)" style={{ padding: '10px 14px' }}>
                  <p className="text-(--text-faint)" style={{ fontSize: '11px', marginBottom: '5px' }}>
                    {message.deptCard.items_label}
                  </p>
                  <div className="flex flex-wrap" style={{ gap: '4px' }}>
                    {message.deptCard.items.map((it) => (
                      <span
                        key={it}
                        className="rounded-full bg-(--surface-2) text-(--text-muted)"
                        style={{ fontSize: '11px', padding: '2px 8px' }}
                      >
                        {it}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* 학과 사무실 전화 — 모바일에서 눌러서 바로 걸 수 있게 tel: 링크 */}
              {message.deptCard.phone && (
                <div className="bg-(--surface-card) border-t border-(--border)" style={{ padding: '8px 14px' }}>
                  <p className="flex items-center gap-1.5 text-(--text-muted)" style={{ fontSize: '11px' }}>
                    <span>📞</span>
                    {message.deptCard.phone.split(',').map((num, i) => (
                      <span key={num}>
                        {i > 0 && <span className="text-(--text-faint)" style={{ margin: '0 4px' }}>·</span>}
                        <a href={`tel:${num.trim()}`} className="text-(--text-muted) hover:text-(--brand)" style={{ textDecoration: 'none' }}>
                          {num.trim()}
                        </a>
                      </span>
                    ))}
                  </p>
                </div>
              )}

              {/* 학과 홈페이지 링크 (DB에 주소가 채워진 학과만) */}
              {message.deptCard.homepage_url && (
                <a
                  href={message.deptCard.homepage_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-center gap-1.5 text-xs font-medium text-(--brand) hover:bg-(--brand-tint) transition bg-(--surface-card) border-t border-(--border)"
                  style={{ padding: '8px', textDecoration: 'none' }}
                >
                  <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                  </svg>
                  {ct.deptHome}
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

          {/* 파일 전송 확인 버튼 (show_buttons=false 인 단일 파일 제안, 대기 중일 때만 표시) */}
          {message.fileOffer && !message.fileOffer.show_buttons && isLatest && pendingFile && (
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                onClick={() => onConfirmFile(pendingFile, true)}
                className="flex items-center justify-center gap-1.5 rounded-lg border text-sm font-bold transition w-20 py-2 border-(--brand) text-(--brand) bg-(--brand-tint) hover:bg-[#e2f1f0]"
              >
                {ct.yes}
              </button>
              <button
                onClick={() => onConfirmFile(pendingFile, false)}
                className="flex items-center justify-center gap-1.5 rounded-lg border text-sm font-bold transition w-20 py-2 border-(--border-strong) text-(--text-muted) bg-(--surface-2) hover:bg-(--surface-2)"
              >
                {ct.no}
              </button>
              </div>
           )}

          {/* 파일 선택 버튼 (사용자가 '응' 확인 후에만 표시) */}
          {message.fileOffer && message.fileOffer.show_buttons && message.fileOffer.files && message.fileOffer.files.length > 0 && (
            <div style={{ marginTop: '14px' }}>
              <p className="text-xs text-(--text-faint)" style={{ marginBottom: '8px' }}>{ct.pickFile}</p>
              <div className="flex flex-wrap gap-2">
                {message.fileOffer.files.map((filename) => {
                  const stem = filename.replace(/\.[^/.]+$/, '')
                  const isDone = downloadedFiles.has(filename)
                  return (
                    <button
                      key={filename}
                      type="button"
                      disabled={isDone}
                      onClick={async () => {
                        await downloadFileWithAuth(`/api/files/${message.fileOffer.topic}/${filename}`, filename)
                        setDownloadedFiles(prev => new Set([...prev, filename]))
                        if (onClearPendingFile) onClearPendingFile()
                      }}
                      className="flex items-center gap-1.5 rounded-lg border text-sm font-medium transition"
                      style={{
                        padding: '6px 12px',
                        borderColor: isDone ? 'var(--text-faint)' : 'var(--brand)',
                        color: isDone ? 'var(--text-faint)' : 'var(--brand)',
                        backgroundColor: isDone ? '#f8f8f8' : 'var(--brand-tint)',
                        cursor: isDone ? 'default' : 'pointer',
                      }}
                    >
                      <svg className="h-3.5 w-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                      </svg>
                      {isDone ? `${stem} ✓` : stem}
                    </button>
                  )
                })}

                {/* 전체 다운로드 버튼 (파일 2개 이상일 때만) */}
                {message.fileOffer.files.length > 1 && (
                  <button
                    type="button"
                    disabled={message.fileOffer.files.every(f => downloadedFiles.has(f))}
                    onClick={async () => {
                      for (const filename of message.fileOffer.files) {
                        if (!downloadedFiles.has(filename)) {
                          await downloadFileWithAuth(`/api/files/${message.fileOffer.topic}/${filename}`, filename)
                        }
                      }
                      setDownloadedFiles(new Set(message.fileOffer.files))
                      if (onClearPendingFile) onClearPendingFile()
                    }}
                    className="flex items-center gap-1.5 rounded-lg border text-sm font-medium transition"
                    style={{
                      padding: '6px 12px',
                      borderColor: message.fileOffer.files.every(f => downloadedFiles.has(f)) ? 'var(--text-faint)' : '#1a5276',
                      color: message.fileOffer.files.every(f => downloadedFiles.has(f)) ? 'var(--text-faint)' : '#1a5276',
                      backgroundColor: message.fileOffer.files.every(f => downloadedFiles.has(f)) ? '#f8f8f8' : '#eaf2f8',
                      cursor: message.fileOffer.files.every(f => downloadedFiles.has(f)) ? 'default' : 'pointer',
                    }}
                  >
                    <svg className="h-3.5 w-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                    </svg>
                    {message.fileOffer.files.every(f => downloadedFiles.has(f)) ? ct.allDone : ct.downloadAll}
                  </button>
                )}
              </div>
            </div>
          )}

          <div className="flex justify-between items-end" style={{ marginTop: '12px' }}>
            <span className="text-xs text-(--text-faint)">{message.time}</span>
            <MessageActions messageId={message.messageId} content={message.content} />
          </div>
        </div>
      </div>
    </div>
  )
}
