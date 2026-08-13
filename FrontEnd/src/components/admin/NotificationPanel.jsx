import { useState, useEffect, useCallback } from 'react'
import { fetchUnanswered, setUnansweredStatus, deleteUnanswered } from '../../api/admins/faq'
import UnansweredAnswerModal from './UnansweredAnswerModal'
import { BTN, BTN_PAD } from './buttonStyles'

/* 헤더 종을 누르면 열리는 알림 패널.
 *
 * 목록 화면으로 넘기지 않고 여기서 바로 처리할 수 있게 둔 이유 —
 * 관리자는 대개 다른 작업(문서 업로드·통계 확인) 중에 알림을 본다. 그때마다 화면을
 * 옮겨야 하면 하던 일이 끊겨서 '나중에'가 되고, 미답변은 쌓이기만 한다.
 * 답변 작성과 제외를 패널 안에서 끝낼 수 있으면 흐름을 끊지 않고 처리된다.
 *
 * 많은 건수를 훑는 것은 목록 화면의 몫이라 여기서는 상위 몇 건만 보여주고
 * 나머지는 '전체 보기'로 넘긴다 — 패널이 길어지면 그냥 작은 목록 화면이 되어 버린다.
 *
 * 여백은 전역 `* { padding: 0 }` 리셋이 Tailwind 유틸을 덮어써서 인라인 style로 준다.
 */

const PREVIEW_LIMIT = 5

function fmtWhen(v) {
  if (!v) return ''
  const diff = (Date.now() - new Date(v).getTime()) / 1000
  if (diff < 60) return '방금'
  if (diff < 3600) return `${Math.floor(diff / 60)}분 전`
  if (diff < 86400) return `${Math.floor(diff / 3600)}시간 전`
  return `${Math.floor(diff / 86400)}일 전`
}

export default function NotificationPanel({ onClose, onCountChange, onOpenList }) {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [answerTarget, setAnswerTarget] = useState(null)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      setRows(await fetchUnanswered('pending'))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function ignore(id) {
    try {
      await setUnansweredStatus(id, 'ignored')
      await load()
      onCountChange?.()
    } catch (e) { setError(e.message) }
  }

  // 되돌릴 수 없어 확인을 받는다. 문구는 목록 화면과 같은 내용을 쓴다 —
  // 같은 동작인데 화면마다 설명이 다르면 어느 쪽이 맞는지 알 수 없다.
  async function remove(row) {
    const ok = window.confirm(
      `이 질문을 완전히 삭제할까요?\n\n"${row.question}"\n\n` +
      '· 되돌릴 수 없습니다.\n' +
      '· 같은 질문이 다시 들어오면 처음부터 다시 수집됩니다.\n' +
      '  (다시 올라오지 않게 하려면 "제외"를 쓰세요)'
    )
    if (!ok) return
    try {
      await deleteUnanswered(row.id)
      await load()
      onCountChange?.()
    } catch (e) { setError(e.message) }
  }

  const shown = rows.slice(0, PREVIEW_LIMIT)

  return (
    <>
      <div
        className="absolute right-0 top-full bg-(--surface-card) rounded-2xl shadow-lg border border-(--border) z-50 overflow-hidden"
        style={{ marginTop: '8px', width: '380px' }}
        /* 패널 안 클릭이 바깥 클릭 감지에 걸려 닫히지 않도록 막는다 */
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-(--border)"
             style={{ padding: '14px 16px' }}>
          <p className="text-sm font-black text-(--text)">미답변 질문</p>
          {rows.length > 0 && (
            <span className="text-xs text-(--text-faint)">{rows.length}건 대기</span>
          )}
        </div>

        <div style={{ maxHeight: '380px', overflowY: 'auto' }}>
          {loading ? (
            <p className="text-sm text-(--text-faint) text-center" style={{ padding: '28px' }}>
              불러오는 중…
            </p>
          ) : error ? (
            <p className="text-sm text-center" style={{ padding: '28px', color: 'var(--danger-text)' }}>
              {error}
            </p>
          ) : rows.length === 0 ? (
            <p className="text-sm text-(--text-faint) text-center" style={{ padding: '28px', lineHeight: 1.6 }}>
              답변을 기다리는 질문이 없습니다.
            </p>
          ) : (
            shown.map((r) => (
              <div key={r.id} className="border-b border-(--border)" style={{ padding: '12px 16px' }}>
                <div className="flex items-start" style={{ gap: '9px' }}>
                  {r.occurrences > 1 && (
                    <span className="shrink-0 rounded-md font-bold"
                          style={{ padding: '2px 7px', fontSize: '11px',
                                   background: 'var(--amber-tint)', color: 'var(--amber-text)' }}>
                      {r.occurrences}회
                    </span>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-bold text-(--text)" style={{ lineHeight: 1.45 }}>
                      {r.question}
                    </p>
                    <p className="text-xs text-(--text-faint)" style={{ marginTop: '3px' }}>
                      {fmtWhen(r.created_at)}
                      {r.topic && ` · ${r.topic}`}
                      {r.is_academic === false && ' · 학사 무관 판정'}
                    </p>
                  </div>
                </div>
                <div className="flex" style={{ gap: '2px', marginTop: '7px', marginLeft: '-4px' }}>
                  <button onClick={() => setAnswerTarget(r)} className={BTN.ghostBrand} style={BTN_PAD}>
                    답변 작성
                  </button>
                  <button onClick={() => ignore(r.id)} className={BTN.ghost} style={BTN_PAD}>
                    제외
                  </button>
                  <button onClick={() => remove(r)} className={BTN.ghostDanger} style={BTN_PAD}>
                    삭제
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {rows.length > PREVIEW_LIMIT && (
          <p className="text-xs text-(--text-faint) text-center border-b border-(--border)"
             style={{ padding: '8px' }}>
            외 {rows.length - PREVIEW_LIMIT}건 더 있습니다
          </p>
        )}

        <button
          onClick={() => { onClose?.(); onOpenList?.() }}
          className="w-full text-xs font-bold text-(--text-muted) hover:bg-(--surface-2) hover:text-(--brand) transition"
          style={{ padding: '12px' }}
        >
          전체 목록에서 보기
        </button>
      </div>

      {/* 답변 모달은 목록 화면과 같은 컴포넌트를 쓴다 — 폼이 두 벌이 되면 한쪽만 고쳐진다 */}
      {answerTarget && (
        <UnansweredAnswerModal
          row={answerTarget}
          onClose={() => setAnswerTarget(null)}
          onSaved={async () => {
            setAnswerTarget(null)
            await load()
            onCountChange?.()
          }}
        />
      )}
    </>
  )
}
