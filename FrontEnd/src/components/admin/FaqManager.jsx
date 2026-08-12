import { useState, useEffect, useCallback } from 'react'
import { fetchFaqs, createFaq, updateFaq, deleteFaq, reloadFaqIndex } from '../../api/admins/faq'
import UnansweredManager from './UnansweredManager'
import { BTN, BTN_PAD, BTN_PAD_LG } from './buttonStyles'

/* FAQ 관리
 *
 * FAQ는 '검수된 답변 1개 + 매칭용 질문 변형 N개' 구조다. 질문이 인덱스에 걸리면 LLM을 건너뛰고
 * 답변이 그대로 나가므로, 변형을 잘못 등록하면 교정 여지 없는 확정 오답이 된다.
 * (실측: '학포 몇 학점부터 가능한가요?'가 학사경고 FAQ에 붙어 있어 무관한 답이 나갔다)
 * 그래서 화면에서 변형을 한눈에 보고 고칠 수 있게 한 줄 = 한 변형으로 편집한다.
 *
 * 저장하면 서버가 메모리 인덱스를 자동으로 다시 만든다 — 재시작 없이 즉시 반영된다.
 *
 * 화면을 '등록된 FAQ'와 '미답변 질문' 두 탭으로 둔 이유
 *   앞으로 FAQ는 관리자가 상상해서 만드는 것이 아니라 학생이 실제로 물었는데 답하지 못한
 *   질문에서 자란다. 두 화면을 메뉴로 갈라 놓으면 '답변 작성 → FAQ 등록'이 한 흐름인데도
 *   메뉴를 오가야 해서 연결이 끊긴다. 기존에 등록된 FAQ는 그대로 유지된다.
 *
 * 여백은 전역 `* { padding: 0 }` 리셋이 Tailwind 유틸을 덮어써서 인라인 style로 준다.
 */

const EMPTY = { answer: '', category: '', questions: '' }

/* tab·pendingCount는 AdminPage가 들고 있는 값을 그대로 받는다.
   자체 상태로 두면 헤더의 종·사이드바 배지와 숫자가 어긋난다 — 관리자가 답변을 처리해도
   사이드바에는 처리 전 건수가 남아 있었다. 갱신도 부모의 폴링 한 곳에서만 한다. */
export default function FaqManager({ tab = 'faqs', onTabChange, pendingCount = 0, onCountChange }) {
  const [faqs, setFaqs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [msg, setMsg] = useState(null)
  const [editing, setEditing] = useState(null)      // { id|null, answer, category, questions }
  const [saving, setSaving] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [query, setQuery] = useState('')
  const setTab = (t) => onTabChange?.(t)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      setFaqs(await fetchFaqs())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  function flash(text) {
    setMsg(text)
    setTimeout(() => setMsg(null), 3000)
  }

  function openNew() { setEditing({ id: null, ...EMPTY }) }

  function openEdit(f) {
    setEditing({
      id: f.id,
      answer: f.answer,
      category: f.category || '',
      questions: (f.questions || []).map((q) => q.text).join('\n'),
    })
  }

  async function save() {
    if (!editing.answer.trim()) { setError('답변을 입력하세요.'); return }
    setSaving(true); setError(null)
    const payload = {
      answer: editing.answer,
      category: editing.category,
      questions: editing.questions.split('\n').map((s) => s.trim()).filter(Boolean),
    }
    try {
      if (editing.id) await updateFaq(editing.id, payload)
      else await createFaq(payload)
      setEditing(null)
      await load()
      flash('저장했습니다. 인덱스가 즉시 반영됐어요.')
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function toggleEnabled(f) {
    try {
      await updateFaq(f.id, { enabled: !f.enabled })
      await load()
    } catch (e) { setError(e.message) }
  }

  async function confirmDelete() {
    const id = deleteTarget.id
    setDeleteTarget(null)
    try {
      await deleteFaq(id)
      await load()
      flash('삭제했습니다.')
    } catch (e) { setError(e.message) }
  }

  async function manualReload() {
    try {
      const r = await reloadFaqIndex()
      flash(`인덱스를 다시 만들었습니다 (질문 ${r.count}개).`)
    } catch (e) { setError(e.message) }
  }

  const q = query.trim().toLowerCase()
  const visible = q
    ? faqs.filter((f) =>
        (f.answer || '').toLowerCase().includes(q) ||
        (f.category || '').toLowerCase().includes(q) ||
        (f.questions || []).some((x) => x.text.toLowerCase().includes(q)))
    : faqs
  const totalQuestions = faqs.reduce((n, f) => n + (f.questions?.length || 0), 0)

  const inputCls = 'w-full border border-(--border) rounded-lg text-sm text-(--text) bg-(--surface-card) outline-none focus:border-(--brand) transition'

  return (
    <div className="flex flex-col flex-1 min-h-0" style={{ gap: '16px' }}>

      {/* 헤더 */}
      <div className="bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) shrink-0"
           style={{ padding: '20px 24px' }}>
        <div className="flex items-center flex-wrap" style={{ gap: '12px' }}>
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-black text-(--text)">FAQ 관리</h2>
            <p className="text-xs text-(--text-faint)" style={{ marginTop: '4px' }}>
              등록된 질문이 매칭되면 AI를 거치지 않고 이 답변을 그대로 내보냅니다 ·
              현재 {faqs.length}건 / 질문 변형 {totalQuestions}개
            </p>
          </div>
          {tab === 'faqs' && (
            <button onClick={openNew} className={`${BTN.primary} shrink-0`} style={BTN_PAD_LG}>
              + FAQ 추가
            </button>
          )}
        </div>
        {/* 탭 — '미답변 질문'에는 대기 건수를 붙인다. 관리자가 이 화면을 열었을 때
            처리할 일이 있는지 한눈에 보여야 한다. */}
        <div className="flex" style={{ gap: '8px', marginTop: '14px' }}>
          <button onClick={() => setTab('faqs')}
                  className={tab === 'faqs' ? BTN.tabOn : BTN.tabOff}
                  style={{ padding: '8px 16px' }}>
            등록된 FAQ
          </button>
          <button onClick={() => setTab('unanswered')}
                  className={`${tab === 'unanswered' ? BTN.tabOn : BTN.tabOff} flex items-center`}
                  style={{ padding: '8px 16px', gap: '7px' }}>
            미답변 질문
            {pendingCount > 0 && (
              <span className="rounded-full font-bold text-white"
                    style={{ background: 'var(--danger-text)', fontSize: '11px', padding: '1px 7px' }}>
                {pendingCount}
              </span>
            )}
          </button>
        </div>

        {tab === 'faqs' && (
          <input value={query} onChange={(e) => setQuery(e.target.value)}
                 placeholder="답변 · 질문 · 분류로 검색"
                 className={inputCls} style={{ padding: '9px 12px', marginTop: '14px' }} />
        )}
        {msg && <p className="text-xs font-bold text-(--brand)" style={{ marginTop: '10px' }}>{msg}</p>}
        {error && <p className="text-xs font-bold" style={{ marginTop: '10px', color: 'var(--danger-text)' }}>{error}</p>}

        {/* 복구용 — 화면에서 저장하면 서버가 알아서 재적재하므로 평소엔 쓸 일이 없다.
            DB를 SQL로 직접 고쳤거나, 저장은 됐는데 재적재가 실패한 경우에만 필요하다.
            버튼으로 크게 두면 매번 눌러야 하는 것처럼 보여서 작은 링크로 내렸다. */}
        {tab === 'faqs' && (
          <button onClick={manualReload}
                  className="text-[11px] text-(--text-faint) hover:text-(--brand) underline transition"
                  style={{ marginTop: '10px' }}
                  title="DB를 직접 수정했거나 반영이 안 될 때만 사용하세요">
            인덱스가 반영되지 않았나요? 다시 적재
          </button>
        )}
      </div>

      {/* 미답변 질문 — 답변을 저장하면 FAQ가 되고 목록이 갱신된다 */}
      {tab === 'unanswered' && (
        <div className="flex-1 min-h-0 overflow-y-auto">
          <UnansweredManager onCountChange={() => { onCountChange?.(); load() }} />
        </div>
      )}

      {/* 등록된 FAQ 목록 */}
      {tab === 'faqs' && (
      <div className="bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) flex-1 min-h-0 overflow-y-auto"
           style={{ padding: '8px 12px 12px' }}>
        {loading && <p className="text-sm text-(--text-faint) text-center" style={{ padding: '40px' }}>불러오는 중…</p>}
        {!loading && visible.length === 0 && (
          <p className="text-sm text-(--text-faint) text-center" style={{ padding: '40px' }}>
            {faqs.length === 0 ? '등록된 FAQ가 없습니다.' : '검색 결과가 없습니다.'}
          </p>
        )}

        {!loading && visible.map((f) => (
          <div key={f.id} className="border-b border-(--border)" style={{ padding: '14px 6px' }}>
            <div className="flex items-start" style={{ gap: '12px' }}>
              <div className="flex-1 min-w-0">
                <div className="flex items-center flex-wrap" style={{ gap: '6px', marginBottom: '6px' }}>
                  {f.category && (
                    <span className="text-[11px] font-bold text-(--brand) bg-(--brand-a10) rounded-full"
                          style={{ padding: '2px 9px' }}>{f.category}</span>
                  )}
                  <span className="text-[11px] text-(--text-faint)">질문 {f.questions?.length || 0}개</span>
                  {!f.enabled && (
                    <span className="text-[11px] font-bold text-amber-600 bg-amber-50 rounded-full"
                          style={{ padding: '2px 9px' }}>사용 안 함</span>
                  )}
                </div>
                {/* 질문을 위에 크게 둔다. 관리자가 목록에서 찾는 것은 '학생이 무엇을
                    물었을 때 나가는 답인가'라서, 답변 본문보다 질문이 먼저 눈에 들어와야 한다.
                    첫 변형을 대표로 굵게 보이고 나머지는 아래에 작게 잇는다. */}
                <p className="text-sm font-bold text-(--text)" style={{ lineHeight: 1.5 }}>
                  {f.questions?.[0]?.text || '질문 변형 없음 — 매칭되지 않습니다'}
                </p>
                {(f.questions?.length || 0) > 1 && (
                  <p className="text-xs text-(--text-faint)" style={{ lineHeight: 1.6, marginTop: '3px' }}>
                    {f.questions.slice(1).map((x) => x.text).join('  ·  ')}
                  </p>
                )}
                <p className="text-sm text-(--text-body)"
                   style={{ lineHeight: 1.6, marginTop: '8px' }}>
                  {f.answer.length > 160 ? f.answer.slice(0, 160) + '…' : f.answer}
                </p>
              </div>
              {/* 행 액션은 붙여서 한 덩어리로 보이게 한다(gap 2px). 떨어뜨리면 각자
                  다른 것을 가리키는 것처럼 읽힌다. */}
              <div className="flex items-center shrink-0" style={{ gap: '2px' }}>
                <button onClick={() => toggleEnabled(f)} className={BTN.ghost} style={BTN_PAD}>
                  {f.enabled ? '비활성' : '활성'}
                </button>
                <button onClick={() => openEdit(f)} className={BTN.ghostBrand} style={BTN_PAD}>
                  수정
                </button>
                <button onClick={() => setDeleteTarget(f)} className={BTN.ghostDanger} style={BTN_PAD}>
                  삭제
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
      )}

      {/* 편집 모달 */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
             style={{ background: 'rgba(15,23,42,.5)', padding: '16px' }}
             onMouseDown={() => !saving && setEditing(null)}>
          <div className="bg-(--surface-card) rounded-2xl shadow-xl border border-(--border) w-full flex flex-col"
               style={{ maxWidth: '640px', maxHeight: '88vh' }}
               onMouseDown={(e) => e.stopPropagation()}>
            <div className="border-b border-(--border) shrink-0" style={{ padding: '18px 22px' }}>
              <h3 className="text-base font-black text-(--text)">{editing.id ? 'FAQ 수정' : 'FAQ 추가'}</h3>
            </div>

            <div className="overflow-y-auto" style={{ padding: '18px 22px' }}>
              <label className="text-xs font-bold text-(--text-muted)">분류 <span className="font-normal text-(--text-faint)">(선택)</span></label>
              <input value={editing.category} onChange={(e) => setEditing({ ...editing, category: e.target.value })}
                     placeholder="예: 학사경고"
                     className={inputCls} style={{ padding: '9px 12px', marginTop: '5px', marginBottom: '16px' }} />

              <label className="text-xs font-bold text-(--text-muted)">답변 <span className="font-normal text-(--text-faint)">(이 문장이 그대로 나갑니다)</span></label>
              <textarea value={editing.answer} onChange={(e) => setEditing({ ...editing, answer: e.target.value })}
                        rows={6}
                        className={inputCls} style={{ padding: '10px 12px', marginTop: '5px', marginBottom: '16px', resize: 'vertical', lineHeight: 1.6 }} />

              <label className="text-xs font-bold text-(--text-muted)">
                질문 변형 <span className="font-normal text-(--text-faint)">(한 줄에 하나 · 학생이 물어볼 만한 표현)</span>
              </label>
              <textarea value={editing.questions} onChange={(e) => setEditing({ ...editing, questions: e.target.value })}
                        rows={7} placeholder={'학사경고 기준이 뭐야\n학사경고 몇 점부터야'}
                        className={inputCls} style={{ padding: '10px 12px', marginTop: '5px', resize: 'vertical', lineHeight: 1.7 }} />
              <p className="text-[11px] text-(--text-faint)" style={{ marginTop: '8px', lineHeight: 1.6 }}>
                변형이 다른 FAQ와 비슷하면 엉뚱한 답변이 나갈 수 있습니다.
                등록 후 <span className="font-bold">faq_health_check</span> 스크립트로 충돌을 확인하세요.
              </p>
            </div>

            <div className="border-t border-(--border) flex shrink-0" style={{ gap: '8px', padding: '14px 22px' }}>
              <button onClick={() => setEditing(null)} disabled={saving}
                      className={`${BTN.tabOff} flex-1`}
                      style={{ padding: '11px' }}>취소</button>
              <button onClick={save} disabled={saving}
                      className={`${BTN.primary} flex-1`}
                      style={{ padding: '11px' }}>{saving ? '저장 중…' : '저장'}</button>
            </div>
          </div>
        </div>
      )}

      {/* 삭제 확인 */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
             style={{ background: 'rgba(15,23,42,.5)', padding: '16px' }}
             onMouseDown={() => setDeleteTarget(null)}>
          <div className="bg-(--surface-card) rounded-2xl shadow-xl border border-(--border) w-full"
               style={{ maxWidth: '400px' }} onMouseDown={(e) => e.stopPropagation()}>
            <div style={{ padding: '20px 22px 16px' }}>
              <p className="text-sm font-black text-(--text)">이 FAQ를 삭제할까요?</p>
              <p className="text-xs text-(--text-muted)" style={{ marginTop: '8px', lineHeight: 1.6 }}>
                {deleteTarget.answer.slice(0, 80)}…
              </p>
              <p className="text-[11px] text-(--text-faint)" style={{ marginTop: '8px' }}>
                질문 변형 {deleteTarget.questions?.length || 0}개도 함께 삭제되며 되돌릴 수 없습니다.
              </p>
            </div>
            <div className="border-t border-(--border) flex">
              <button onClick={() => setDeleteTarget(null)}
                      className="flex-1 text-sm font-bold text-(--text-muted) hover:bg-(--surface-2) transition"
                      style={{ padding: '13px' }}>취소</button>
              <button onClick={confirmDelete}
                      className="flex-1 text-sm font-bold border-l border-(--border) transition"
                      style={{ padding: '13px', color: 'var(--danger-text)' }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--danger-tint)')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = '')}>삭제</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
