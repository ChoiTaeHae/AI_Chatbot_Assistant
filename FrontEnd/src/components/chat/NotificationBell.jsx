import { useState, useEffect, useRef, useCallback } from 'react'
import { fetchNotifications, fetchNotificationCount, markNotificationRead } from '../../api/notifications'

/* 학생용 알림 종 — 답을 못 받았던 내 질문에 답변이 등록되면 빨간 점이 붙는다.
 *
 * 관리자 쪽 NotificationPanel과 모양은 같지만 컴포넌트를 나눴다. 저쪽은 패널 안에서
 * 답변을 '작성'하고 이쪽은 '확인'한다 — 하는 일이 반대라 한 컴포넌트로 묶으면
 * 역할 분기가 파일 전체에 퍼진다. 여기서는 종·배지·패널을 한 파일에 담아
 * ChatPage 헤더가 이 컴포넌트 하나만 놓으면 끝나게 했다.
 *
 * 답변을 패널에 다 펼치지 않고 채팅으로 넘기는 이유 — 답변에는 표·목록이 들어가고
 * 그건 채팅 말풍선(MessageBubble)이 이미 렌더할 줄 안다. 패널에서 다시 렌더하면
 * 마크다운 처리가 두 벌이 되어 한쪽만 고쳐진다.
 *
 * 여백은 전역 `* { padding: 0 }` 리셋이 Tailwind 유틸을 덮어써서 인라인 style로 준다.
 */

const POLL_MS = 30_000

const T = {
  ko: { title: '알림', empty: '새 알림이 없습니다.', answered: '답변이 등록되었어요',
        loading: '불러오는 중…', bell: '알림', unreadOne: '읽지 않은 알림', now: '방금',
        min: '분 전', hour: '시간 전', day: '일 전' },
  en: { title: 'Notifications', empty: 'No new notifications.', answered: 'An answer has been posted',
        loading: 'Loading…', bell: 'Notifications', unreadOne: 'unread notifications', now: 'just now',
        min: 'm ago', hour: 'h ago', day: 'd ago' },
  zh: { title: '通知', empty: '暂无新通知。', answered: '答复已登记',
        loading: '加载中…', bell: '通知', unreadOne: '未读通知', now: '刚刚',
        min: '分钟前', hour: '小时前', day: '天前' },
}

function fmtWhen(v, t) {
  if (!v) return ''
  const diff = (Date.now() - new Date(v).getTime()) / 1000
  if (diff < 60) return t.now
  if (diff < 3600) return `${Math.floor(diff / 60)}${t.min}`
  if (diff < 86400) return `${Math.floor(diff / 3600)}${t.hour}`
  return `${Math.floor(diff / 86400)}${t.day}`
}

export default function NotificationBell({ lang = 'ko', onOpenAnswer }) {
  const t = T[lang] || T.ko
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const wrapRef = useRef(null)

  const loadCount = useCallback(async () => {
    // 폴링 실패는 조용히 넘긴다 — 네트워크가 잠깐 끊겼다고 채팅 화면에 오류를 띄우면
    // 정작 하던 대화가 방해받는다. 다음 주기에 다시 시도된다.
    try { setUnread((await fetchNotificationCount()).unread || 0) } catch { /* 무시 */ }
  }, [])

  const loadRows = useCallback(async () => {
    setLoading(true)
    try { setRows(await fetchNotifications()) } catch { setRows([]) } finally { setLoading(false) }
  }, [])

  /* 새로고침 없이 점이 붙게 하는 두 축.
   *
   *   · 주기 폴링   — 화면을 보고 있는 동안 최대 POLL_MS 안에 붙는다.
   *   · 탭 복귀 감지 — 다른 탭·창에 갔다가 돌아오면 그 순간 확인한다.
   *
   * 폴링만으로는 부족하다. 브라우저는 백그라운드 탭의 setInterval을 1분 이상으로 늦추거나
   * 아예 멈추기 때문에, 학생이 다른 일을 하다 돌아왔을 때 점이 한참 뒤에야 붙는다.
   * 실제 사용은 대부분 '돌아왔을 때'라서 체감상 이쪽이 더 중요하다.
   *
   * 숨어 있는 동안에는 폴링도 건너뛴다 — 어차피 보이지 않는 화면이라 요청만 낭비된다.
   * 다시 보일 때 visibilitychange가 즉시 채워 준다.
   */
  useEffect(() => {
    loadCount()
    const wake = () => { if (document.visibilityState === 'visible') loadCount() }
    const id = setInterval(wake, POLL_MS)
    document.addEventListener('visibilitychange', wake)
    window.addEventListener('focus', wake)
    return () => {
      clearInterval(id)
      document.removeEventListener('visibilitychange', wake)
      window.removeEventListener('focus', wake)
    }
  }, [loadCount])

  // 바깥 클릭으로 닫기
  useEffect(() => {
    if (!open) return
    function onDown(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  function toggle() {
    const next = !open
    setOpen(next)
    if (next) loadRows()          // 열 때마다 새로 읽는다 — 목록은 폴링하지 않는다
  }

  async function pick(row) {
    setOpen(false)
    onOpenAnswer?.(row)           // 채팅에 질문·답변을 띄운다
    if (row.is_read) return
    // 읽음 처리가 실패해도 답변은 이미 보여 줬다. 점이 남을 뿐이라 흐름을 막지 않는다.
    try {
      await markNotificationRead(row.id)
      setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, is_read: true } : r)))
      setUnread((n) => Math.max(0, n - 1))
    } catch { /* 무시 */ }
  }

  return (
    <div className="relative" ref={wrapRef}>
      <button
        onClick={toggle}
        className="relative inline-flex items-center justify-center h-9 w-9 rounded-lg text-white hover:bg-white/10 transition"
        aria-label={unread > 0 ? `${t.bell} ${unread}` : t.bell}
        title={unread > 0 ? `${unread} ${t.unreadOne}` : t.bell}
      >
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none"
             stroke="currentColor" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round"
                d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
        </svg>
        {unread > 0 && (
          // 테두리를 헤더 배경색(--brand)으로 줘서 종 위에 점이 얹힌 것처럼 보이게 한다.
          // 관리자 헤더는 흰 배경이라 --surface-card를 쓰지만 여기는 브랜드색 헤더다.
          <span className="absolute rounded-full"
                style={{ top: '5px', right: '5px', width: '9px', height: '9px',
                         background: '#ef4444', border: '2px solid var(--brand)' }} />
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 top-full bg-(--surface-card) rounded-2xl shadow-lg border border-(--border) z-50 overflow-hidden"
          style={{ marginTop: '8px', width: '340px', maxWidth: 'calc(100vw - 24px)' }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between border-b border-(--border)"
               style={{ padding: '13px 16px' }}>
            <p className="text-sm font-black text-(--text)">{t.title}</p>
            {unread > 0 && (
              <span className="text-xs font-bold" style={{ color: 'var(--brand)' }}>{unread}</span>
            )}
          </div>

          <div style={{ maxHeight: '360px', overflowY: 'auto' }}>
            {loading ? (
              <p className="text-sm text-(--text-faint) text-center" style={{ padding: '28px' }}>{t.loading}</p>
            ) : rows.length === 0 ? (
              <p className="text-sm text-(--text-faint) text-center"
                 style={{ padding: '28px', lineHeight: 1.6 }}>{t.empty}</p>
            ) : (
              rows.map((r) => (
                <button
                  key={r.id}
                  onClick={() => pick(r)}
                  className="w-full text-left border-b border-(--border) hover:bg-(--surface-2) transition"
                  style={{ padding: '12px 16px' }}
                >
                  <div className="flex items-start" style={{ gap: '9px' }}>
                    {/* 안 읽은 것만 점을 붙인다 — 읽은 알림도 목록에는 남겨
                        나중에 답변을 다시 열어 볼 수 있게 한다 */}
                    <span className="shrink-0 rounded-full"
                          style={{ marginTop: '6px', width: '7px', height: '7px',
                                   background: r.is_read ? 'transparent' : 'var(--brand)' }} />
                    <div className="flex-1 min-w-0">
                      <p className={`text-sm text-(--text) ${r.is_read ? 'font-medium' : 'font-bold'}`}
                         style={{ lineHeight: 1.45 }}>
                        {r.question}
                      </p>
                      <p className="text-xs text-(--text-faint)" style={{ marginTop: '3px' }}>
                        {t.answered} · {fmtWhen(r.notified_at, t)}
                      </p>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
