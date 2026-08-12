import { useState, useEffect, useCallback } from 'react'
import { fetchUnanswered, setUnansweredStatus } from '../../api/admins/faq'
import UnansweredAnswerModal from './UnansweredAnswerModal'
import { BTN, BTN_PAD } from './buttonStyles'

/* 미답변 질문 → FAQ 전환
 *
 * 챗봇이 답하지 못한 질문이 여기 쌓인다. 관리자가 답변을 쓰면 그대로 FAQ가 되고, 서버가
 * 인덱스를 재적재해 다음 학생부터 바로 답을 받는다 — FAQ가 짐작이 아니라 '실제로 막힌
 * 질문'에서 자라게 하는 것이 목적이다.
 *
 * 화면에서 두 가지를 반드시 살린다.
 *   ① 물어본 횟수(occurrences) — 무엇을 먼저 답할지 정하는 유일한 신호다. 목록이 20건만
 *      넘어도 이게 없으면 순서를 정할 수 없어, 숫자를 배지로 크게 띄우고 기본 정렬로 쓴다.
 *   ② 질문 변형 입력칸 — 학생은 등록된 문장 그대로 묻지 않는다. 원 질문 하나만 등록하면
 *      표현이 조금 달라져도 또 못 찾아, 같은 질문이 미답변 목록에 다시 쌓인다.
 *
 * 여백은 전역 `* { padding: 0 }` 리셋이 Tailwind 유틸을 덮어써서 인라인 style로 준다.
 */

const TABS = [
  { id: 'pending',  label: '확인 대기' },
  { id: 'answered', label: '답변 완료' },
  { id: 'ignored',  label: '제외함' },
  // LLM이 학사 무관·부적절로 자동 분류한 것. 지우지 않고 남겨 오판을 확인할 수 있게 한다.
  { id: 'filtered', label: '자동 걸러짐' },
]

function fmtDate(v) {
  if (!v) return ''
  const d = new Date(v)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export default function UnansweredManager({ onCountChange }) {
  const [tab, setTab] = useState('pending')
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [msg, setMsg] = useState(null)
  const [answerTarget, setAnswerTarget] = useState(null)   // 답변 작성 중인 행

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      setRows(await fetchUnanswered(tab))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [tab])

  useEffect(() => { load() }, [load])

  function flash(t) {
    setMsg(t)
    setTimeout(() => setMsg(null), 3500)
  }

  async function ignore(id) {
    try {
      await setUnansweredStatus(id, 'ignored')
      await load()
      onCountChange?.()
      flash('목록에서 제외했습니다.')
    } catch (e) { setError(e.message) }
  }

  async function restore(id) {
    try {
      await setUnansweredStatus(id, 'pending')
      await load()
      onCountChange?.()
      flash('확인 대기로 되돌렸습니다.')
    } catch (e) { setError(e.message) }
  }

  const cardCls = 'bg-(--surface-card) rounded-2xl shadow-sm border border-(--border)'
  const inputCls = 'w-full border border-(--border) rounded-xl text-(--text) bg-(--surface-card) outline-none focus:border-(--brand) transition'
  const inputStyle = { padding: '10px 12px', fontSize: '14px' }

  return (
    <div className="flex-1 flex flex-col" style={{ gap: '16px' }}>
      {/* 제목은 두지 않는다 — 이 컴포넌트는 'FAQ 관리' 화면의 한 탭으로 들어가므로
          바깥에 이미 제목이 있다. 상태 필터와 안내 한 줄만 남긴다. */}
      <div className={cardCls} style={{ padding: '18px 22px' }}>
        <p className="text-xs text-(--text-faint)" style={{ lineHeight: 1.6 }}>
          챗봇이 답하지 못한 질문입니다. 답변을 저장하면 곧바로 FAQ가 되어 다음 학생부터 적용됩니다.
        </p>

        <div className="flex flex-wrap" style={{ gap: '8px', marginTop: '14px' }}>
          {TABS.map((t) => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={tab === t.id ? BTN.tabOn : BTN.tabOff}
              style={{ padding: '8px 14px' }}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {msg && (
        <div className="rounded-xl text-sm" style={{
          padding: '12px 16px', background: 'var(--brand-a8)', color: 'var(--brand)',
        }}>{msg}</div>
      )}
      {error && (
        <div className="rounded-xl text-sm" style={{
          padding: '12px 16px', background: 'var(--danger-tint)', color: 'var(--danger-text)',
        }}>{error}</div>
      )}

      <div className={cardCls} style={{ padding: '20px 22px' }}>
        {loading ? (
          <p className="text-(--text-faint) text-sm">불러오는 중...</p>
        ) : rows.length === 0 ? (
          <p className="text-(--text-faint) text-sm">
            {tab === 'pending' ? '확인할 미답변 질문이 없습니다.' : '해당 항목이 없습니다.'}
          </p>
        ) : (
          <div className="flex flex-col" style={{ gap: '10px' }}>
            {rows.map((r) => (
              <div key={r.id} className="border border-(--border) rounded-xl"
                   style={{ padding: '14px 16px' }}>
                <div className="flex items-start" style={{ gap: '12px' }}>
                  {/* 물어본 횟수 — 우선순위를 정하는 유일한 신호라 가장 먼저 눈에 들어와야 한다 */}
                  <div className="shrink-0 rounded-lg text-center"
                       style={{
                         padding: '6px 10px', minWidth: '46px',
                         background: r.occurrences > 1 ? 'var(--amber-tint)' : 'var(--surface-2)',
                         color: r.occurrences > 1 ? 'var(--amber-text)' : 'var(--text-muted)',
                       }}>
                    <div className="font-black" style={{ fontSize: '16px' }}>{r.occurrences}</div>
                    <div style={{ fontSize: '10px' }}>회</div>
                  </div>

                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-bold text-(--text)" style={{ lineHeight: 1.5 }}>
                      {r.question}
                    </p>
                    <div className="flex flex-wrap items-center text-xs text-(--text-faint)"
                         style={{ gap: '8px', marginTop: '6px' }}>
                      {r.topic && <span>토픽 {r.topic}</span>}
                      {r.rewritten && <span>· 검색어 “{r.rewritten}”</span>}
                      <span>· {fmtDate(r.created_at)}</span>
                      {/* 선별 결과. null이면 아직 분류 전이거나 분류에 실패한 것이라 목록에는 그대로 둔다 */}
                      {r.is_academic === false && (
                        <span style={{ color: 'var(--danger-text)' }}>· 학사 무관 판정</span>
                      )}
                      {r.triage_reason && <span>· {r.triage_reason}</span>}
                    </div>
                  </div>

                  <div className="shrink-0 flex" style={{ gap: '2px' }}>
                    {tab === 'pending' && (
                      <>
                        <button
                          onClick={() => setAnswerTarget(r)}
                          className={BTN.ghostBrand} style={BTN_PAD}>
                          답변 작성
                        </button>
                        <button onClick={() => ignore(r.id)}
                          className={BTN.ghost} style={BTN_PAD}>
                          제외
                        </button>
                      </>
                    )}
                    {(tab === 'ignored' || tab === 'filtered') && (
                      <button onClick={() => restore(r.id)}
                        className={BTN.ghost} style={BTN_PAD}>
                        되돌리기
                      </button>
                    )}
                    {tab === 'answered' && r.faq_id && (
                      <span className="text-xs text-(--text-faint)" style={{ padding: '8px 4px' }}>
                        FAQ #{r.faq_id}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 답변 작성 — 헤더 알림 팝업과 같은 모달을 쓴다(폼이 갈라지지 않게) */}
      {answerTarget && (
        <UnansweredAnswerModal
          row={answerTarget}
          onClose={() => setAnswerTarget(null)}
          onSaved={async (r) => {
            setAnswerTarget(null)
            await load()
            onCountChange?.()
            flash(`FAQ로 등록했습니다. (질문 ${r.question_count}개 · 인덱스 ${r.reloaded}개 재적재)`)
          }}
        />
      )}
    </div>
  )
}
