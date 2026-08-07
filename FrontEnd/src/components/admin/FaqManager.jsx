import { useState, useEffect, useCallback } from 'react'
import { fetchFaqs, createFaq, updateFaq, deleteFaq, reloadFaqIndex } from '../../api/admins/faq'

/* FAQ 관리
 *
 * FAQ는 '검수된 답변 1개 + 매칭용 질문 변형 N개' 구조다. 질문이 인덱스에 걸리면 LLM을 건너뛰고
 * 답변이 그대로 나가므로, 변형을 잘못 등록하면 교정 여지 없는 확정 오답이 된다.
 * (실측: '학포 몇 학점부터 가능한가요?'가 학사경고 FAQ에 붙어 있어 무관한 답이 나갔다)
 * 그래서 화면에서 변형을 한눈에 보고 고칠 수 있게 한 줄 = 한 변형으로 편집한다.
 *
 * 저장하면 서버가 메모리 인덱스를 자동으로 다시 만든다 — 재시작 없이 즉시 반영된다.
 * 여백은 전역 `* { padding: 0 }` 리셋이 Tailwind 유틸을 덮어써서 인라인 style로 준다.
 */

const EMPTY = { answer: '', category: '', questions: '' }

export default function FaqManager() {
  const [faqs, setFaqs] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [msg, setMsg] = useState(null)
  const [editing, setEditing] = useState(null)      // { id|null, answer, category, questions }
  const [saving, setSaving] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [query, setQuery] = useState('')

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
          <button onClick={openNew}
                  className="bg-(--brand) text-white rounded-lg text-sm font-black hover:bg-(--brand-hover) transition shrink-0"
                  style={{ padding: '10px 18px' }}>
            + FAQ 추가
          </button>
        </div>
        <input value={query} onChange={(e) => setQuery(e.target.value)}
               placeholder="답변 · 질문 · 분류로 검색"
               className={inputCls} style={{ padding: '9px 12px', marginTop: '14px' }} />
        {msg && <p className="text-xs font-bold text-(--brand)" style={{ marginTop: '10px' }}>{msg}</p>}
        {error && <p className="text-xs font-bold text-red-500" style={{ marginTop: '10px' }}>{error}</p>}

        {/* 복구용 — 화면에서 저장하면 서버가 알아서 재적재하므로 평소엔 쓸 일이 없다.
            DB를 SQL로 직접 고쳤거나, 저장은 됐는데 재적재가 실패한 경우에만 필요하다.
            버튼으로 크게 두면 매번 눌러야 하는 것처럼 보여서 작은 링크로 내렸다. */}
        <button onClick={manualReload}
                className="text-[11px] text-(--text-faint) hover:text-(--brand) underline transition"
                style={{ marginTop: '10px' }}
                title="DB를 직접 수정했거나 반영이 안 될 때만 사용하세요">
          인덱스가 반영되지 않았나요? 다시 적재
        </button>
      </div>

      {/* 목록 */}
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
                <p className="text-sm text-(--text)" style={{ lineHeight: 1.5, marginBottom: '6px' }}>
                  {f.answer.length > 160 ? f.answer.slice(0, 160) + '…' : f.answer}
                </p>
                <p className="text-xs text-(--text-faint)" style={{ lineHeight: 1.6 }}>
                  {(f.questions || []).map((x) => x.text).join('  ·  ') || '질문 변형 없음 — 매칭되지 않습니다'}
                </p>
              </div>
              <div className="flex items-center shrink-0" style={{ gap: '6px' }}>
                <button onClick={() => toggleEnabled(f)}
                        className="border border-(--border) rounded-lg text-xs font-bold text-(--text-muted) hover:bg-(--surface-2) transition"
                        style={{ padding: '6px 10px' }}>
                  {f.enabled ? '비활성' : '활성'}
                </button>
                <button onClick={() => openEdit(f)}
                        className="border border-(--brand-a20) rounded-lg text-xs font-bold text-(--brand) hover:bg-(--brand-a5) transition"
                        style={{ padding: '6px 12px' }}>수정</button>
                <button onClick={() => setDeleteTarget(f)}
                        className="border border-(--border) rounded-lg text-xs font-bold text-red-500 hover:bg-red-50 transition"
                        style={{ padding: '6px 12px' }}>삭제</button>
              </div>
            </div>
          </div>
        ))}
      </div>

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
                      className="flex-1 border border-(--border) rounded-lg text-sm font-bold text-(--text-muted) hover:bg-(--surface-2) transition disabled:opacity-50"
                      style={{ padding: '11px' }}>취소</button>
              <button onClick={save} disabled={saving}
                      className="flex-1 bg-(--brand) text-white rounded-lg text-sm font-black hover:bg-(--brand-hover) transition disabled:opacity-50"
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
                      className="flex-1 text-sm font-bold text-red-500 border-l border-(--border) hover:bg-red-50 transition"
                      style={{ padding: '13px' }}>삭제</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
