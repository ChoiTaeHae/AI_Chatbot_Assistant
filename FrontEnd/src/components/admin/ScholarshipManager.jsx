import { useState, useEffect, useMemo, useRef } from 'react'
import { fetchScholarships, createScholarship, updateScholarship, deleteScholarship } from '../../api/admins/scholarships'
import { fetchFiles, setScholarshipLink, uploadFile, deleteFile } from '../../api/admins/files'

const TEAL = 'var(--brand)'
const EMPTY = { name: '', kind: '장학금', scope: '교내', category: '', amount: '', eligibility: '', period: '', end_at: '', link: '' }

/** 서버 ISO(초 포함) → datetime-local 입력값(YYYY-MM-DDTHH:mm) */
function toLocalInput(iso) {
  if (!iso) return ''
  return iso.slice(0, 16)
}

export default function ScholarshipManager() {
  const [list, setList] = useState([])
  const [filesByTopic, setFilesByTopic] = useState({})
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState(null)          // { type, text }

  const [mode, setMode] = useState('list')       // 'list' | 'form'
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState(EMPTY)
  const [saving, setSaving] = useState(false)
  const [fileSearch, setFileSearch] = useState('')
  const [fileTab, setFileTab] = useState('scholarship')   // 파일 첨부 목록 탭: 'scholarship'(장학금) | 'work_study'(근로)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef(null)

  async function loadList() {
    try { setList(await fetchScholarships()) }
    catch (e) { setMsg({ type: 'error', text: e.message }) }
  }
  async function loadFiles() {
    try { const d = await fetchFiles(); setFilesByTopic(d.files || {}) }
    catch (e) { console.error(e) }
  }
  useEffect(() => { (async () => { setLoading(true); await Promise.all([loadList(), loadFiles()]); setLoading(false) })() }, [])

  const grouped = useMemo(() => {
    const g = { 장학금: [], 근로: [] }
    for (const s of list) (g[s.kind] || (g[s.kind] = [])).push(s)
    return g
  }, [list])

  const fileCounts = useMemo(() => ({
    scholarship: (filesByTopic['scholarship'] || []).length,
    work_study: (filesByTopic['work_study'] || []).length,
  }), [filesByTopic])
  const shownFiles = useMemo(() => {
    const q = fileSearch.trim().toLowerCase()
    const inTab = filesByTopic[fileTab] || []
    return q ? inTab.filter((f) => f.name.toLowerCase().includes(q)) : inTab
  }, [filesByTopic, fileTab, fileSearch])

  function openAdd() { setForm(EMPTY); setEditingId(null); setFileSearch(''); setFileTab('scholarship'); setMsg(null); setMode('form') }
  function openEdit(s) {
    setForm({
      name: s.name || '', kind: s.kind || '장학금', scope: s.scope || '교내', category: s.category || '', amount: s.amount || '',
      eligibility: s.eligibility || '', period: s.period || '', end_at: toLocalInput(s.end_at),
      link: s.link || '',
    })
    setEditingId(s.id); setFileSearch(''); setFileTab(s.kind === '근로' ? 'work_study' : 'scholarship'); setMsg(null); setMode('form')
  }
  function backToList() { setMode('list'); setEditingId(null); loadList() }

  function setField(k, v) { setForm((p) => ({ ...p, [k]: v })) }

  async function save() {
    if (!form.name.trim()) { setMsg({ type: 'error', text: '장학금 이름은 필수예요.' }); return }
    setSaving(true); setMsg(null)
    const payload = {
      ...form,
      category: form.category || null, amount: form.amount || null, eligibility: form.eligibility || null,
      period: form.period || null, link: form.link || null,
      end_at: form.end_at ? form.end_at : null,
    }
    try {
      if (editingId) {
        await updateScholarship(editingId, payload)
        setMsg({ type: 'success', text: '수정됐어요.' })
      } else {
        const res = await createScholarship(payload)
        setEditingId(res.id)   // 파일 첨부 가능하도록 편집 모드로 전환
        setMsg({ type: 'success', text: '저장됐어요. 아래에서 파일을 첨부하세요.' })
      }
      await Promise.all([loadList(), loadFiles()])
    } catch (e) {
      setMsg({ type: 'error', text: e.message })
    } finally { setSaving(false) }
  }

  async function remove(s) {
    if (!confirm(`'${s.name}' 장학금을 삭제할까요? (연결된 파일은 삭제되지 않고 연결만 해제돼요)`)) return
    try { await deleteScholarship(s.id); await loadList() }
    catch (e) { alert(e.message) }
  }

  // 파일 연결/해제/대표
  async function toggleFile(f) {
    const linkedHere = f.scholarship_id === editingId
    try {
      await setScholarshipLink(f.id, linkedHere ? null : editingId, false)
      await Promise.all([loadFiles(), loadList()])
    } catch (e) { alert(e.message) }
  }
  async function makePrimary(f) {
    try { await setScholarshipLink(f.id, editingId, true); await Promise.all([loadFiles(), loadList()]) }
    catch (e) { alert(e.message) }
  }
  // 업로드 → 'scholarship' topic에 저장 + 현재 장학금에 자동 연결
  async function handleUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      await uploadFile(file, fileTab, editingId, false)   // 현재 탭(장학금/근로) topic으로 저장 + 연결
      await Promise.all([loadFiles(), loadList()])
    } catch (err) { alert(err.message) }
    finally { setUploading(false); if (fileInputRef.current) fileInputRef.current.value = '' }
  }
  async function handleDeleteFile(f) {
    if (!confirm(`'${f.name}' 파일을 삭제할까요? (연결도 함께 해제됩니다)`)) return
    try { await deleteFile(f.topic, f.name); await Promise.all([loadFiles(), loadList()]) }
    catch (err) { alert(err.message) }
  }

  const inputCls = 'w-full text-sm text-(--text) border border-(--border) rounded-lg bg-(--surface-card) outline-none focus:border-(--brand)'

  // ─────────────────────────────── 목록 뷰 ───────────────────────────────
  if (mode === 'list') {
    return (
      <div className="flex-1 bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) flex flex-col" style={{ padding: '32px', gap: '18px' }}>
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-black text-(--text)">장학금·근로 관리</h2>
            <p className="text-xs text-(--text-faint) mt-0.5">'장학금·근로 둘러보기'에 노출되는 항목을 추가·수정하고 파일을 연결합니다</p>
          </div>
          <button onClick={openAdd} className="flex items-center bg-(--brand) text-white text-sm font-bold hover:bg-(--brand-hover) transition rounded-xl" style={{ gap: '6px', padding: '9px 16px' }}>
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
            추가
          </button>
        </div>

        {msg && <div className={`text-xs font-medium px-4 py-2 rounded-xl ${msg.type === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`}>{msg.text}</div>}

        {loading ? (
          <p className="text-center text-(--text-faint) text-sm" style={{ padding: '40px' }}>불러오는 중…</p>
        ) : list.length === 0 ? (
          <div className="flex flex-col items-center justify-center text-(--text-faint)" style={{ padding: '50px 0', gap: '8px' }}>
            <p className="text-sm font-medium">등록된 항목이 없습니다</p>
            <p className="text-xs">오른쪽 상단 '추가'로 시작하세요</p>
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto flex flex-col" style={{ gap: '18px' }}>
            {['장학금', '근로'].map((k) => (grouped[k] || []).length > 0 && (
              <div key={k}>
                <p className="text-sm font-bold" style={{ marginBottom: '8px', color: TEAL }}>{k === '근로' ? '💼' : '🎓'} {k} <span className="text-(--text-faint) font-normal">({grouped[k].length})</span></p>
                <div className="border border-(--border) rounded-xl overflow-hidden">
                  {grouped[k].map((s) => (
                    <div key={s.id} className="flex items-center gap-3 border-b border-(--border) last:border-b-0 hover:bg-(--surface-2) transition" style={{ padding: '11px 14px' }}>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-[11px] font-semibold text-white rounded-full shrink-0" style={{ padding: '1px 8px', background: s.scope === '교외' ? '#0ea5a0' : 'var(--text-faint)' }}>{s.scope}</span>
                          <span className="font-semibold text-(--text) text-sm">{s.name}</span>
                          {s.category && <span className="text-[11px] text-(--text-muted) bg-(--surface-2) rounded-full" style={{ padding: '1px 8px' }}>{s.category}</span>}
                          {s.amount && <span className="text-[11px] font-semibold" style={{ color: TEAL }}>{s.amount}</span>}
                          {s.expired && <span className="text-[11px] font-semibold text-red-600 bg-red-50 rounded-full" style={{ padding: '1px 8px' }}>기간마감</span>}
                        </div>
                        <div className="flex items-center gap-2 text-[11px] text-(--text-faint)" style={{ marginTop: '2px' }}>
                          {s.period && <span>🗓 {s.period}</span>}
                          <span>📎 파일 {s.files?.length || 0}</span>
                        </div>
                      </div>
                      <button onClick={() => openEdit(s)} className="text-xs font-semibold text-(--brand) hover:underline shrink-0">수정</button>
                      <button onClick={() => remove(s)} className="text-xs font-semibold text-red-500 hover:underline shrink-0">삭제</button>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  // ─────────────────────────────── 추가/수정 폼 ───────────────────────────────
  return (
    <div className="flex-1 bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) flex flex-col overflow-y-auto" style={{ padding: '32px', gap: '16px' }}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <button onClick={backToList} className="text-(--text-faint) hover:text-(--text-body)" aria-label="목록으로">
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" /></svg>
          </button>
          <h2 className="text-base font-black text-(--text)">{editingId ? `${form.kind} 수정` : `${form.kind} 추가`}</h2>
        </div>
        <button onClick={save} disabled={saving} className="bg-(--brand) text-white text-sm font-bold hover:bg-(--brand-hover) transition disabled:opacity-50 rounded-xl" style={{ padding: '9px 18px' }}>
          {saving ? '저장 중…' : '저장'}
        </button>
      </div>

      {msg && <div className={`text-xs font-medium px-4 py-2 rounded-xl ${msg.type === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`}>{msg.text}</div>}

      {/* 기본 정보 */}
      <div className="grid grid-cols-2" style={{ gap: '14px' }}>
        <label className="col-span-2 flex flex-col gap-1">
          <span className="text-xs font-bold text-(--text-muted)">이름 *</span>
          <input className={inputCls} style={{ padding: '8px 10px' }} value={form.name} onChange={(e) => setField('name', e.target.value)} placeholder="예: 서울인재대학장학금 / 국가근로장학금" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-bold text-(--text-muted)">종류 *</span>
          <select className={inputCls} style={{ padding: '8px 10px' }} value={form.kind} onChange={(e) => { setField('kind', e.target.value); setFileTab(e.target.value === '근로' ? 'work_study' : 'scholarship') }}>
            <option value="장학금">장학금</option>
            <option value="근로">근로</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-bold text-(--text-muted)">구분 *</span>
          <select className={inputCls} style={{ padding: '8px 10px' }} value={form.scope} onChange={(e) => setField('scope', e.target.value)}>
            <option value="교내">교내</option>
            <option value="교외">교외</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-bold text-(--text-muted)">카테고리 (그룹)</span>
          <input className={inputCls} style={{ padding: '8px 10px' }} value={form.category} onChange={(e) => setField('category', e.target.value)} placeholder="예: 성적우수 / 근로 / 지자체" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-bold text-(--text-muted)">금액</span>
          <input className={inputCls} style={{ padding: '8px 10px' }} value={form.amount} onChange={(e) => setField('amount', e.target.value)} placeholder="예: 연간 400만원 / 전액" />
        </label>
        <label className="col-span-2 flex flex-col gap-1">
          <span className="text-xs font-bold text-(--text-muted)">지원 조건 (한 줄)</span>
          <input className={inputCls} style={{ padding: '8px 10px' }} value={form.eligibility} onChange={(e) => setField('eligibility', e.target.value)} placeholder="예: 공고문에서 확인 / 직전학기 3.0 이상" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-bold text-(--text-muted)">신청 기간 (화면 표시)</span>
          <input className={inputCls} style={{ padding: '8px 10px' }} value={form.period} onChange={(e) => setField('period', e.target.value)} placeholder="예: 2026. 3. 24 10:00 ~ 3. 31 16:00 까지" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs font-bold text-(--text-muted)">마감 일시 <span className="text-(--text-faint) font-normal">(지나면 자동 '기간마감', 상시는 비움)</span></span>
          <input type="datetime-local" className={inputCls} style={{ padding: '8px 10px' }} value={form.end_at} onChange={(e) => setField('end_at', e.target.value)} />
        </label>
        <label className="col-span-2 flex flex-col gap-1">
          <span className="text-xs font-bold text-(--text-muted)">외부 공고 링크</span>
          <input className={inputCls} style={{ padding: '8px 10px' }} value={form.link} onChange={(e) => setField('link', e.target.value)} placeholder="https://..." />
        </label>
      </div>

      {/* 파일 첨부 */}
      <div className="border-t border-(--border)" style={{ paddingTop: '16px' }}>
        <div className="flex items-center justify-between" style={{ marginBottom: '4px' }}>
          <p className="text-sm font-bold text-(--text)">파일 첨부</p>
          {editingId && (
            <>
              <input ref={fileInputRef} type="file" className="hidden"
                accept=".pdf,.docx,.pptx,.xlsx,.hwp,.hwpx,.txt,.md,.jpg,.jpeg,.png" onChange={handleUpload} />
              <button onClick={() => fileInputRef.current?.click()} disabled={uploading}
                className="flex items-center gap-1 text-xs font-bold text-white bg-(--brand) hover:bg-(--brand-hover) transition disabled:opacity-50 rounded-lg" style={{ padding: '6px 12px' }}>
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
                {uploading ? '업로드 중…' : '파일 업로드'}
              </button>
            </>
          )}
        </div>
        {!editingId ? (
          <p className="text-xs text-(--text-faint)">먼저 <b>저장</b>하면 이 장학금에 파일을 업로드·연결할 수 있어요.</p>
        ) : (
          <>
            <p className="text-xs text-(--text-faint)" style={{ marginBottom: '10px' }}>파일을 <b>업로드</b>하면 이 항목에 바로 연결돼요(현재 탭 종류로 저장). 기존 파일은 체크해서 연결하고, 대표 1개를 지정하세요.</p>
            <div className="flex items-center gap-2" style={{ marginBottom: '10px' }}>
              {[['scholarship', '장학금 파일'], ['work_study', '근로 파일']].map(([t, label]) => {
                const active = fileTab === t
                return (
                  <button key={t} onClick={() => setFileTab(t)} className="text-xs font-semibold transition"
                    style={{ padding: '5px 12px', borderRadius: '999px', background: active ? TEAL : 'var(--surface-2)', color: active ? '#fff' : 'var(--text-muted)' }}>
                    {label} ({fileCounts[t] || 0})
                  </button>
                )
              })}
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-(--border)" style={{ padding: '6px 10px', marginBottom: '10px' }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-faint)" strokeWidth="2"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" strokeLinecap="round" /></svg>
              <input value={fileSearch} onChange={(e) => setFileSearch(e.target.value)} placeholder="파일 검색" className="flex-1 outline-none bg-transparent text-sm" />
            </div>
            <div className="border border-(--border) rounded-xl overflow-hidden" style={{ maxHeight: '320px', overflowY: 'auto' }}>
              {shownFiles.length === 0 ? (
                <p className="text-center text-(--text-faint) text-xs" style={{ padding: '20px' }}>이 탭에 파일이 없어요. 위 '파일 업로드'로 올리세요.</p>
              ) : shownFiles.map((f) => {
                const linkedHere = f.scholarship_id === editingId
                const linkedOther = f.scholarship_id && !linkedHere
                return (
                  <div key={f.id} className="flex items-center gap-2 border-b border-(--border) last:border-b-0" style={{ padding: '8px 12px', background: linkedHere ? 'var(--brand-tint)' : 'transparent' }}>
                    <input type="checkbox" checked={linkedHere} onChange={() => toggleFile(f)} style={{ accentColor: TEAL }} />
                    <span className="flex-1 min-w-0 truncate text-xs text-(--text-body)" title={f.name}>{f.name}</span>
                    {linkedOther && <span className="text-[10px] text-amber-600 bg-amber-50 rounded-full shrink-0" style={{ padding: '1px 7px' }}>연결됨: {f.scholarship_name}</span>}
                    {linkedHere && (
                      f.is_primary
                        ? <span className="text-[10px] font-bold text-white rounded-full shrink-0" style={{ padding: '1px 8px', background: TEAL }}>대표</span>
                        : <button onClick={() => makePrimary(f)} className="text-[10px] font-semibold shrink-0 hover:underline" style={{ color: TEAL }}>대표로</button>
                    )}
                    <button onClick={() => handleDeleteFile(f)} className="text-(--text-faint) hover:text-red-500 transition shrink-0" title="파일 삭제" aria-label="파일 삭제">
                      <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" /></svg>
                    </button>
                  </div>
                )
              })}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
