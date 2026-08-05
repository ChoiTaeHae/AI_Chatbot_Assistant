import { useState, useEffect, useMemo, useRef } from 'react'
import { fetchScholarships, createScholarship, updateScholarship, deleteScholarship, fetchDepartments } from '../../api/admins/scholarships'
import { fetchFiles, linkScholarshipFile, unlinkScholarshipFile, uploadFile, deleteFile } from '../../api/admins/files'

const TEAL = 'var(--brand)'
const EMPTY = {
  name: '', scope: '교내', category: '', amount: '', eligibility: '', period: '', end_at: '', link: '',
  // 맞춤 설문 매칭 요건 — 전부 선택(비우면 '무관' → 필터 통과)
  req_region: '', req_region_basis: '', req_min_gpa: '', req_grade: [], req_income: '',
  req_age_max: '', req_major_field: [], req_departments: [],
  req_multichild: false, req_foreigner: false, req_disabled: false, req_independent: false, req_veteran: false,
  req_excellent: false, req_flags_preferential: false,
}

const BASIS_OPTS = [['', '무관'], ['본인', '본인 거주'], ['부모', '부모 거주']]
const GRADE_OPTS = [['신입', '신입생 (1학년)'], ['재학', '재학생 (1·2·3·4학년)'], ['2학년이상', '2학년 이상'], ['3학년이상', '3학년 이상'], ['대학원', '대학원']]   // 다중선택
// 소득 요건 = 국가장학금 학자금 지원구간. '복지'(복지자격) 또는 'N구간 이하'
const INCOME_OPTS = [
  ['', '무관'],
  ['복지', '복지자격(기초·차상위)'],
  ['1', '1구간 이하'], ['2', '2구간 이하'], ['3', '3구간 이하'], ['4', '4구간 이하'], ['5', '5구간 이하'],
  ['6', '6구간 이하'], ['7', '7구간 이하'], ['8', '8구간 이하'], ['9', '9구간 이하'], ['10', '10구간 이하'],
]
// 레거시 값 정규화: 기초·차상위→복지자격, 구간/복지→그대로, 중위%등→무관(관리자 재선택)
const _INCOME_LEGACY = { 기초: '복지', 차상위: '복지' }
const normIncome = (v) => (!v ? '' : (_INCOME_LEGACY[v] || (/^(복지|10|[1-9])$/.test(v) ? v : '')))
const MAJOR_OPTS = [['인문사회', '인문·사회'], ['예술체육', '예술·체육'], ['이공', '이공'], ['의학계열', '의학계열']]   // 다중선택
const REQ_FLAGS = [
  ['req_excellent', '성적 우수'],
  ['req_multichild', '다자녀'], ['req_foreigner', '외국인·유학생'], ['req_independent', '자취·독립·기숙사'],
  ['req_disabled', '장애'], ['req_veteran', '보훈·유공자'],
]
// 필수/우대(req_flags_preferential)의 적용 대상 = 성적우수를 뺀 사회배려형 플래그들.
// (성적우수는 별도 양방향 필터라 필수/우대와 무관)
const COND_FLAG_KEYS = ['req_multichild', 'req_foreigner', 'req_independent', 'req_disabled', 'req_veteran']

/** 서버 ISO(초 포함) → datetime-local 입력값(YYYY-MM-DDTHH:mm) */
function toLocalInput(iso) {
  if (!iso) return ''
  return iso.slice(0, 16)
}

/** 대상 학과 다중선택 — 검색 콤보박스. 선택은 칩으로, 검색해서 목록에서 추가. */
function DeptMultiSelect({ all, selected, onChange }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const boxRef = useRef(null)
  useEffect(() => {
    const onDoc = (e) => { if (boxRef.current && !boxRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])
  const kw = q.trim().toLowerCase()
  const filtered = all.filter((d) => !selected.includes(d) && (!kw || d.toLowerCase().includes(kw))).slice(0, 60)
  return (
    <div ref={boxRef}>
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5" style={{ marginBottom: '6px' }}>
          {selected.map((d) => (
            <span key={d} className="inline-flex items-center gap-1 rounded-full text-white" style={{ fontSize: '11.5px', padding: '3px 5px 3px 10px', background: TEAL }}>
              {d}
              <button type="button" onClick={() => onChange(selected.filter((x) => x !== d))} className="inline-flex items-center justify-center hover:bg-white/25 rounded-full" style={{ width: '16px', height: '16px', fontSize: '10px' }} aria-label="제거">✕</button>
            </span>
          ))}
        </div>
      )}
      <div className="relative">
        <input
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true) }}
          onFocus={() => setOpen(true)}
          placeholder="학과 검색해서 추가 (여러 개 선택 · 비우면 무관)"
          className="w-full text-sm text-(--text) border border-(--border) rounded-lg bg-(--surface-card) outline-none focus:border-(--brand)"
          style={{ padding: '8px 10px' }}
        />
        {open && filtered.length > 0 && (
          <div className="absolute left-0 right-0 z-20 border border-(--border) rounded-lg bg-(--surface-card) shadow-lg overflow-y-auto" style={{ top: 'calc(100% + 4px)', maxHeight: '220px' }}>
            {filtered.map((d) => (
              <button type="button" key={d} onClick={() => { onChange([...selected, d]); setQ('') }}
                className="w-full text-left text-sm text-(--text-body) hover:bg-(--brand-tint) transition" style={{ padding: '7px 12px' }}>
                {d}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
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
  const [uploading, setUploading] = useState(false)
  const [pendingFile, setPendingFile] = useState(null)   // 저장(생성) 시 함께 첨부할 파일
  const [departments, setDepartments] = useState([])     // 대상 학과 다중선택용 학과명 목록
  const [openCats, setOpenCats] = useState({})           // 목록 뷰: 카테고리별 드롭다운 펼침 상태
  const [query, setQuery] = useState('')                 // 목록 뷰: 장학금 검색어
  const fileInputRef = useRef(null)
  const newFileInputRef = useRef(null)

  async function loadList() {
    try { setList(await fetchScholarships()) }
    catch (e) { setMsg({ type: 'error', text: e.message }) }
  }
  async function loadFiles() {
    try { const d = await fetchFiles(); setFilesByTopic(d.files || {}) }
    catch (e) { console.error(e) }
  }
  useEffect(() => { (async () => {
    setLoading(true)
    await Promise.all([loadList(), loadFiles()])
    fetchDepartments().then(setDepartments).catch(() => {})
    setLoading(false)
  })() }, [])

  // 근로 롤백 — 장학금만 관리
  const scholarships = useMemo(() => list.filter((s) => s.kind !== '근로'), [list])
  // 검색 — 이름·카테고리·금액·지원조건으로 필터 (비우면 전체)
  const searching = query.trim() !== ''
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return scholarships
    return scholarships.filter((s) =>
      (s.name || '').toLowerCase().includes(q) ||
      (s.category || '').toLowerCase().includes(q) ||
      (s.amount || '').toLowerCase().includes(q) ||
      (s.eligibility || '').toLowerCase().includes(q)
    )
  }, [scholarships, query])
  // 카테고리별 그룹 (드롭다운). 카테고리 없으면 '미분류'로 묶고 맨 뒤에.
  const groupedByCat = useMemo(() => {
    const map = {}
    for (const s of filtered) {
      const cat = s.category || '미분류'
      ;(map[cat] ||= []).push(s)
    }
    return Object.entries(map).sort((a, b) => {
      if (a[0] === '미분류') return 1
      if (b[0] === '미분류') return -1
      return a[0].localeCompare(b[0], 'ko')
    })
  }, [filtered])
  const allCatsOpen = groupedByCat.length > 0 && groupedByCat.every(([c]) => openCats[c])
  const toggleAllCats = () => setOpenCats(allCatsOpen ? {} : Object.fromEntries(groupedByCat.map(([c]) => [c, true])))

  const shownFiles = useMemo(() => {
    const q = fileSearch.trim().toLowerCase()
    const inTab = filesByTopic['scholarship'] || []
    return q ? inTab.filter((f) => f.name.toLowerCase().includes(q)) : inTab
  }, [filesByTopic, fileSearch])

  function openAdd() { setForm(EMPTY); setEditingId(null); setPendingFile(null); setFileSearch(''); setMsg(null); setMode('form') }
  function openEdit(s) {
    setForm({
      name: s.name || '', scope: s.scope || '교내', category: s.category || '', amount: s.amount || '',
      eligibility: s.eligibility || '', period: s.period || '', end_at: toLocalInput(s.end_at), link: s.link || '',
      req_region: s.req_region || '', req_region_basis: s.req_region_basis || '',
      req_min_gpa: s.req_min_gpa ?? '', req_grade: s.req_grade ? s.req_grade.split(',') : [], req_income: normIncome(s.req_income),
      req_age_max: s.req_age_max ?? '', req_major_field: s.req_major_field ? s.req_major_field.split(',') : [],
      req_departments: s.req_departments ? s.req_departments.split(',') : [],
      req_multichild: !!s.req_multichild, req_foreigner: !!s.req_foreigner, req_disabled: !!s.req_disabled,
      req_independent: !!s.req_independent, req_veteran: !!s.req_veteran, req_excellent: !!s.req_excellent,
      req_flags_preferential: !!s.req_flags_preferential,
    })
    setEditingId(s.id); setPendingFile(null); setFileSearch(''); setMsg(null); setMode('form')
  }
  function backToList() { setMode('list'); setEditingId(null); loadList() }

  function setField(k, v) { setForm((p) => ({ ...p, [k]: v })) }
  // 배열 필드(학년·전공 다중선택) 토글 — p[k]가 배열, p 전체가 아님에 주의
  const toggleArr = (k, v) => setForm((p) => ({ ...p, [k]: p[k].includes(v) ? p[k].filter((x) => x !== v) : [...p[k], v] }))

  async function save() {
    if (!form.name.trim()) { setMsg({ type: 'error', text: '장학금 이름은 필수예요.' }); return }
    setSaving(true); setMsg(null)
    const payload = {
      ...form,
      kind: '장학금',
      category: form.category || null, amount: form.amount || null, eligibility: form.eligibility || null,
      period: form.period || null, link: form.link || null, end_at: form.end_at || null,
      req_region: form.req_region || null, req_region_basis: form.req_region_basis || null,
      req_grade: form.req_grade.length ? form.req_grade.join(',') : null,
      req_income: form.req_income || null,
      req_major_field: form.req_major_field.length ? form.req_major_field.join(',') : null,
      req_departments: form.req_departments.length ? form.req_departments.join(',') : null,
      req_min_gpa: form.req_min_gpa === '' ? null : Number(form.req_min_gpa),
      req_age_max: form.req_age_max === '' ? null : Number(form.req_age_max),
    }
    try {
      if (editingId) {
        await updateScholarship(editingId, payload)
        setMsg({ type: 'success', text: '수정됐어요.' })
      } else {
        const res = await createScholarship(payload)
        setEditingId(res.id)   // 편집 모드로 전환 → 파일 추가/연결 가능
        if (pendingFile) {
          await uploadFile(pendingFile, 'scholarship', res.id, true)   // 선택한 파일을 대표로 첨부
          setPendingFile(null)
        }
        setMsg({ type: 'success', text: '추가됐어요. 아래에서 파일을 더 붙이거나 연결할 수 있어요.' })
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

  // 파일 연결/해제/대표 — 한 파일을 여러 장학금에 공유 연결 가능
  async function toggleFile(f) {
    const linkedHere = (f.scholarships || []).some((x) => x.scholarship_id === editingId)
    try {
      if (linkedHere) await unlinkScholarshipFile(f.id, editingId)
      else await linkScholarshipFile(f.id, editingId, false)
      await Promise.all([loadFiles(), loadList()])
    } catch (e) { alert(e.message) }
  }
  async function makePrimary(f) {
    try { await linkScholarshipFile(f.id, editingId, true); await Promise.all([loadFiles(), loadList()]) }
    catch (e) { alert(e.message) }
  }
  // 편집 중 새 파일 업로드 → 'scholarship' topic + 현재 장학금에 자동 연결
  async function handleUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    try {
      await uploadFile(file, 'scholarship', editingId, false)
      await Promise.all([loadFiles(), loadList()])
    } catch (err) { alert(err.message) }
    finally { setUploading(false); if (fileInputRef.current) fileInputRef.current.value = '' }
  }
  async function handleDeleteFile(f) {
    if (!confirm(`'${f.name}' 파일을 삭제할까요? (연결된 모든 장학금에서 해제됩니다)`)) return
    try { await deleteFile(f.topic, f.name); await Promise.all([loadFiles(), loadList()]) }
    catch (err) { alert(err.message) }
  }

  const inputCls = 'w-full text-sm text-(--text) border border-(--border) rounded-lg bg-(--surface-card) outline-none focus:border-(--brand)'
  const labelCls = 'text-xs font-bold text-(--text-muted)'
  // 사회배려형 대상 조건이 하나라도 켜져야 필수/우대가 의미 있음 (안 켜면 토글 비활성 + ✓ 숨김)
  const hasCondFlags = COND_FLAG_KEYS.some((k) => form[k])

  // ─────────────────────────────── 목록 뷰 ───────────────────────────────
  if (mode === 'list') {
    return (
      <div className="flex-1 bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) flex flex-col" style={{ padding: '32px', gap: '18px' }}>
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-black text-(--text)">장학금 관리</h2>
            <p className="text-xs text-(--text-faint) mt-0.5">'장학금 둘러보기'·맞춤 설문에 쓰이는 장학금을 추가·수정하고 파일·요건을 함께 넣습니다</p>
          </div>
          <button onClick={openAdd} className="flex items-center bg-(--brand) text-white text-sm font-bold hover:bg-(--brand-hover) transition rounded-xl" style={{ gap: '6px', padding: '9px 16px' }}>
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
            장학금 정보 추가
          </button>
        </div>

        {msg && <div className={`text-xs font-medium px-4 py-2 rounded-xl ${msg.type === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`}>{msg.text}</div>}

        {loading ? (
          <p className="text-center text-(--text-faint) text-sm" style={{ padding: '40px' }}>불러오는 중…</p>
        ) : scholarships.length === 0 ? (
          <div className="flex flex-col items-center justify-center text-(--text-faint)" style={{ padding: '50px 0', gap: '8px' }}>
            <p className="text-sm font-medium">등록된 장학금이 없습니다</p>
            <p className="text-xs">오른쪽 상단 '장학금 정보 추가'로 시작하세요</p>
          </div>
        ) : (
          <>
            {/* 검색 */}
            <div className="flex items-center gap-2 rounded-xl border border-(--border) bg-(--surface-card)" style={{ padding: '8px 12px' }}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-faint)" strokeWidth="2"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" strokeLinecap="round" /></svg>
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="장학금 검색 (이름·카테고리·금액·지원조건)" className="flex-1 outline-none bg-transparent text-sm text-(--text)" />
              {searching && <button onClick={() => setQuery('')} className="text-(--text-faint) hover:text-(--text-body) shrink-0" aria-label="검색 지우기">✕</button>}
            </div>

            <div className="flex items-center justify-between">
              <p className="text-[11px] text-(--text-faint)">
                {searching ? `검색 결과 ${filtered.length}건 · 카테고리 ${groupedByCat.length}` : `카테고리 ${groupedByCat.length} · 장학금 ${scholarships.length}`}
              </p>
              {!searching && <button onClick={toggleAllCats} className="text-xs font-semibold text-(--brand) hover:underline">{allCatsOpen ? '모두 접기' : '모두 펼치기'}</button>}
            </div>
            {groupedByCat.length === 0 ? (
              <div className="flex flex-col items-center justify-center text-(--text-faint)" style={{ padding: '40px 0', gap: '6px' }}>
                <p className="text-sm font-medium">'{query.trim()}' 검색 결과가 없어요</p>
                <p className="text-xs">이름·카테고리·금액·지원조건에서 찾습니다</p>
              </div>
            ) : (
            <div className="flex-1 overflow-y-auto flex flex-col" style={{ gap: '10px' }}>
              {groupedByCat.map(([cat, items]) => {
                const open = searching || !!openCats[cat]
                return (
                  <div key={cat} className="border border-(--border) rounded-xl overflow-hidden">
                    {/* 카테고리 헤더 (드롭다운) */}
                    <button
                      onClick={() => setOpenCats((p) => ({ ...p, [cat]: !p[cat] }))}
                      className="flex items-center gap-2 w-full bg-(--surface-2) hover:brightness-95 transition text-left"
                      style={{ padding: '11px 14px' }}
                    >
                      <svg className={`h-4 w-4 text-(--text-faint) transition-transform shrink-0 ${open ? '' : '-rotate-90'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" /></svg>
                      <span className="font-bold text-(--text) text-sm">{cat}</span>
                      <span className="rounded-full font-semibold text-white text-[11px] shrink-0" style={{ padding: '1px 8px', background: TEAL }}>{items.length}</span>
                    </button>

                    {open && (
                      <div>
                        {items.map((s) => (
                          <div key={s.id} className="flex items-center gap-3 border-t border-(--border) hover:bg-(--surface-2) transition" style={{ padding: '11px 14px' }}>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-[11px] font-semibold text-white rounded-full shrink-0" style={{ padding: '1px 8px', background: s.scope === '교외' ? '#0ea5a0' : 'var(--text-faint)' }}>{s.scope}</span>
                                <span className="font-semibold text-(--text) text-sm">{s.name}</span>
                                {s.amount && <span className="text-[11px] font-semibold" style={{ color: TEAL }}>{s.amount}</span>}
                                {s.expired && <span className="text-[11px] font-semibold text-red-600 bg-red-50 rounded-full" style={{ padding: '1px 8px' }}>기간마감</span>}
                              </div>
                              <div className="flex items-center gap-2 text-[11px] text-(--text-faint)" style={{ marginTop: '2px' }}>
                                {s.period && <span><span className="emoji">🗓</span> {s.period}</span>}
                                <span><span className="emoji">📎</span> 파일 {s.files?.length || 0}</span>
                                {(s.req_region || s.req_min_gpa != null || s.req_income || s.req_multichild || s.req_foreigner || s.req_disabled || s.req_independent || s.req_veteran || s.req_excellent) && (
                                  <span style={{ color: TEAL }}><span className="emoji">🎯</span> 요건 설정됨</span>
                                )}
                              </div>
                            </div>
                            <button onClick={() => openEdit(s)} className="text-xs font-semibold text-(--brand) hover:underline shrink-0">수정</button>
                            <button onClick={() => remove(s)} className="text-xs font-semibold text-red-500 hover:underline shrink-0">삭제</button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
            )}
          </>
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
          <h2 className="text-base font-black text-(--text)">{editingId ? '장학금 정보 수정' : '장학금 정보 추가'}</h2>
        </div>
        <button onClick={save} disabled={saving} className="bg-(--brand) text-white text-sm font-bold hover:bg-(--brand-hover) transition disabled:opacity-50 rounded-xl" style={{ padding: '9px 18px' }}>
          {saving ? '저장 중…' : (editingId ? '저장' : '추가')}
        </button>
      </div>

      {msg && <div className={`text-xs font-medium px-4 py-2 rounded-xl ${msg.type === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`}>{msg.text}</div>}

      {/* 기본 정보 */}
      <div className="grid grid-cols-2" style={{ gap: '14px' }}>
        <label className="col-span-2 flex flex-col gap-1">
          <span className={labelCls}>이름 *</span>
          <input className={inputCls} style={{ padding: '8px 10px' }} value={form.name} onChange={(e) => setField('name', e.target.value)} placeholder="예: 서울인재대학장학금" />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>구분 *</span>
          <select className={inputCls} style={{ padding: '8px 10px' }} value={form.scope} onChange={(e) => setField('scope', e.target.value)}>
            <option value="교내">교내</option>
            <option value="교외">교외</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>카테고리 (그룹)</span>
          <input className={inputCls} style={{ padding: '8px 10px' }} value={form.category} onChange={(e) => setField('category', e.target.value)} placeholder="예: 성적우수 / 지자체 / 생활비" />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>금액</span>
          <input className={inputCls} style={{ padding: '8px 10px' }} value={form.amount} onChange={(e) => setField('amount', e.target.value)} placeholder="예: 연간 400만원 / 전액" />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>마감 일시 <span className="text-(--text-faint) font-normal">(상시는 비움)</span></span>
          <input type="datetime-local" className={inputCls} style={{ padding: '8px 10px' }} value={form.end_at} onChange={(e) => setField('end_at', e.target.value)} />
        </label>
        <label className="col-span-2 flex flex-col gap-1">
          <span className={labelCls}>지원 조건 (한 줄, 화면 표시)</span>
          <input className={inputCls} style={{ padding: '8px 10px' }} value={form.eligibility} onChange={(e) => setField('eligibility', e.target.value)} placeholder="예: 공고문에서 확인 / 직전학기 3.0 이상" />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>신청 기간 (화면 표시)</span>
          <input className={inputCls} style={{ padding: '8px 10px' }} value={form.period} onChange={(e) => setField('period', e.target.value)} placeholder="예: 2026. 3. 24 ~ 3. 31" />
        </label>
        <label className="flex flex-col gap-1">
          <span className={labelCls}>외부 공고 링크</span>
          <input className={inputCls} style={{ padding: '8px 10px' }} value={form.link} onChange={(e) => setField('link', e.target.value)} placeholder="https://..." />
        </label>
      </div>

      {/* 지원 요건 (맞춤 설문 매칭용) */}
      <div className="border-t border-(--border)" style={{ paddingTop: '16px' }}>
        <p className="text-sm font-bold text-(--text)">🎯 지원 요건 <span className="text-xs font-normal text-(--text-faint)">— 맞춤 설문 매칭용 · 비운 칸은 '무관'(모두 대상)</span></p>
        <div className="grid grid-cols-2" style={{ gap: '14px', marginTop: '12px' }}>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>대상 지역</span>
            <input className={inputCls} style={{ padding: '8px 10px' }} value={form.req_region} onChange={(e) => setField('req_region', e.target.value)} placeholder="예: 화성시 / 서울 (비우면 무관)" />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>지역 기준</span>
            <select className={inputCls} style={{ padding: '8px 10px' }} value={form.req_region_basis} onChange={(e) => setField('req_region_basis', e.target.value)}>
              {BASIS_OPTS.map(([v, l]) => <option key={v || 'none'} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>최소 학점</span>
            <input type="number" step="0.1" min="0" max="4.5" className={inputCls} style={{ padding: '8px 10px' }} value={form.req_min_gpa} onChange={(e) => setField('req_min_gpa', e.target.value)} placeholder="예: 3.0 (비우면 무관)" />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>나이 상한</span>
            <input type="number" min="15" max="99" className={inputCls} style={{ padding: '8px 10px' }} value={form.req_age_max} onChange={(e) => setField('req_age_max', e.target.value)} placeholder="예: 34 (비우면 무관)" />
          </label>
          <label className="flex flex-col gap-1">
            <span className={labelCls}>학자금 지원구간 (상한)</span>
            <select className={inputCls} style={{ padding: '8px 10px' }} value={form.req_income} onChange={(e) => setField('req_income', e.target.value)}>
              {INCOME_OPTS.map(([v, l]) => <option key={v || 'none'} value={v}>{l}</option>)}
            </select>
          </label>
        </div>

        {/* 학년 요건 · 전공계열 — 다중 선택 (고른 것 중 하나라도 해당하면 대상 · 안 고르면 무관) */}
        <p className={labelCls} style={{ marginTop: '14px', marginBottom: '8px' }}>학년 요건 <span className="font-normal text-(--text-faint)">(여러 개 선택 가능 · 안 고르면 무관)</span></p>
        <div className="flex flex-wrap gap-2">
          {GRADE_OPTS.map(([v, l]) => {
            const on = form.req_grade.includes(v)
            return (
              <button key={v} type="button" onClick={() => toggleArr('req_grade', v)} className="rounded-full border transition" style={{
                fontSize: '12px', padding: '6px 13px', fontWeight: on ? 700 : 500,
                borderColor: on ? 'var(--brand)' : 'var(--border)',
                background: on ? 'var(--brand)' : 'transparent',
                color: on ? '#fff' : 'var(--text-muted)',
              }}>{on ? '✓ ' : ''}{l}</button>
            )
          })}
        </div>
        <p className={labelCls} style={{ marginTop: '14px', marginBottom: '8px' }}>전공계열 <span className="font-normal text-(--text-faint)">(여러 개 선택 가능 · 안 고르면 무관)</span></p>
        <div className="flex flex-wrap gap-2">
          {MAJOR_OPTS.map(([v, l]) => {
            const on = form.req_major_field.includes(v)
            return (
              <button key={v} type="button" onClick={() => toggleArr('req_major_field', v)} className="rounded-full border transition" style={{
                fontSize: '12px', padding: '6px 13px', fontWeight: on ? 700 : 500,
                borderColor: on ? 'var(--brand)' : 'var(--border)',
                background: on ? 'var(--brand)' : 'transparent',
                color: on ? '#fff' : 'var(--text-muted)',
              }}>{on ? '✓ ' : ''}{l}</button>
            )
          })}
        </div>

        <p className={labelCls} style={{ marginTop: '14px', marginBottom: '8px' }}>대상 학과 <span className="font-normal text-(--text-faint)">(특정 학과 전용일 때 · 여러 개 선택 · 안 고르면 무관)</span></p>
        <DeptMultiSelect all={departments} selected={form.req_departments} onChange={(v) => setField('req_departments', v)} />

        <p className={labelCls} style={{ marginTop: '14px', marginBottom: '8px' }}>대상 조건 <span className="font-normal text-(--text-faint)">(다자녀·장애·보훈·자취·외국인 등 · 아래 '필수/우대'로 성격 지정)</span></p>
        <div className="flex flex-wrap gap-2">
          {REQ_FLAGS.map(([key, label]) => {
            const on = form[key]
            return (
              <button key={key} type="button" onClick={() => setField(key, !on)} className="rounded-full border transition" style={{
                fontSize: '12px', padding: '6px 13px', fontWeight: on ? 700 : 500,
                borderColor: on ? 'var(--brand)' : 'var(--border)',
                background: on ? 'var(--brand)' : 'transparent',
                color: on ? '#fff' : 'var(--text-muted)',
              }}>
                {on ? '✓ ' : ''}{label}
              </button>
            )
          })}
        </div>
        {/* 대상 조건 성격: 필수(거름) vs 우대(안 거름·일반 학생 포함). 위 사회배려형 플래그를 켜야 활성화 */}
        <div className="flex items-center flex-wrap gap-2" style={{ marginTop: '10px', opacity: hasCondFlags ? 1 : 0.5 }}>
          <span className="text-[11px] font-bold text-(--text-muted)">대상 조건 성격</span>
          {[[false, '필수 — 이 대상만 (하나라도 해당해야)'], [true, '우대 — 일반 학생도 포함 (안내용)']].map(([val, lbl]) => {
            const on = hasCondFlags && form.req_flags_preferential === val
            return (
              <button key={String(val)} type="button" disabled={!hasCondFlags} onClick={() => setField('req_flags_preferential', val)} className="rounded-full border transition disabled:cursor-not-allowed" style={{
                fontSize: '11px', padding: '4px 11px', fontWeight: on ? 700 : 500,
                borderColor: on ? 'var(--brand)' : 'var(--border)',
                background: on ? 'var(--brand)' : 'transparent',
                color: on ? '#fff' : 'var(--text-muted)',
              }}>
                {on ? '✓ ' : ''}{lbl}
              </button>
            )
          })}
          {!hasCondFlags && <span className="text-[10px] text-(--text-faint)">— 다자녀·외국인·자취·장애·보훈 중 하나를 켜면 지정할 수 있어요</span>}
        </div>
      </div>

      {/* 파일 */}
      <div className="border-t border-(--border)" style={{ paddingTop: '16px' }}>
        <p className="text-sm font-bold text-(--text)" style={{ marginBottom: '8px' }}>📎 파일</p>

        {!editingId ? (
          // 생성 모드 — 파일을 미리 골라두면 '추가' 시 함께 업로드(대표)된다. (RAG 지식 추가처럼 정보+파일 한 번에)
          <>
            <input ref={newFileInputRef} type="file" className="hidden"
              accept=".pdf,.docx,.pptx,.xlsx,.hwp,.hwpx,.txt,.md,.jpg,.jpeg,.png"
              onChange={(e) => setPendingFile(e.target.files?.[0] || null)} />
            <div className="flex items-center gap-2 flex-wrap">
              <button onClick={() => newFileInputRef.current?.click()}
                className="flex items-center gap-1 text-xs font-bold text-(--brand) border border-(--brand) rounded-lg hover:bg-(--brand-tint) transition" style={{ padding: '7px 13px' }}>
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
                파일 선택
              </button>
              {pendingFile ? (
                <span className="text-xs text-(--text-body) inline-flex items-center gap-2 bg-(--surface-2) rounded-lg" style={{ padding: '6px 10px' }}>
                  <span className="truncate" style={{ maxWidth: '260px' }} title={pendingFile.name}>{pendingFile.name}</span>
                  <button onClick={() => { setPendingFile(null); if (newFileInputRef.current) newFileInputRef.current.value = '' }} className="text-(--text-faint) hover:text-red-500" aria-label="선택 취소">✕</button>
                </span>
              ) : (
                <span className="text-xs text-(--text-faint)">선택한 파일은 <b>추가</b> 시 함께 첨부돼요. (여러 파일·기존 파일 연결은 추가 후 가능)</span>
              )}
            </div>
          </>
        ) : (
          // 편집 모드 — 즉시 업로드 + 기존 파일 체크 연결(여러 장학금 공유) + 대표 지정
          <>
            <div className="flex items-center justify-between" style={{ marginBottom: '4px' }}>
              <p className="text-xs text-(--text-faint)">파일을 <b>업로드</b>하면 이 장학금에 바로 연결돼요. 기존 파일은 체크해 연결하고, 대표 1개를 지정하세요. <b>한 파일을 여러 장학금에 체크</b>하면 공유됩니다.</p>
              <input ref={fileInputRef} type="file" className="hidden"
                accept=".pdf,.docx,.pptx,.xlsx,.hwp,.hwpx,.txt,.md,.jpg,.jpeg,.png" onChange={handleUpload} />
              <button onClick={() => fileInputRef.current?.click()} disabled={uploading}
                className="shrink-0 flex items-center gap-1 text-xs font-bold text-white bg-(--brand) hover:bg-(--brand-hover) transition disabled:opacity-50 rounded-lg" style={{ padding: '6px 12px', marginLeft: '10px' }}>
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
                {uploading ? '업로드 중…' : '파일 업로드'}
              </button>
            </div>
            <div className="flex items-center gap-2 rounded-lg border border-(--border)" style={{ padding: '6px 10px', margin: '10px 0' }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-faint)" strokeWidth="2"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" strokeLinecap="round" /></svg>
              <input value={fileSearch} onChange={(e) => setFileSearch(e.target.value)} placeholder="파일 검색" className="flex-1 outline-none bg-transparent text-sm" />
            </div>
            <div className="border border-(--border) rounded-xl overflow-hidden" style={{ maxHeight: '300px', overflowY: 'auto' }}>
              {shownFiles.length === 0 ? (
                <p className="text-center text-(--text-faint) text-xs" style={{ padding: '20px' }}>파일이 없어요. 위 '파일 업로드'로 올리세요.</p>
              ) : shownFiles.map((f) => {
                const links = f.scholarships || []
                const here = links.find((x) => x.scholarship_id === editingId)
                const linkedHere = !!here
                const others = links.filter((x) => x.scholarship_id !== editingId)
                return (
                  <div key={f.id} className="flex items-center gap-2 border-b border-(--border) last:border-b-0" style={{ padding: '8px 12px', background: linkedHere ? 'var(--brand-tint)' : 'transparent' }}>
                    <input type="checkbox" checked={linkedHere} onChange={() => toggleFile(f)} style={{ accentColor: TEAL }} />
                    <span className="flex-1 min-w-0 truncate text-xs text-(--text-body)" title={f.name}>{f.name}</span>
                    {others.length > 0 && (
                      <span className="text-[10px] text-amber-600 bg-amber-50 rounded-full shrink-0 truncate" style={{ padding: '1px 7px', maxWidth: '170px' }}
                        title={`다른 장학금에도 연결됨: ${others.map((x) => x.scholarship_name).join(', ')}`}>
                        공유: {others.map((x) => x.scholarship_name).join(', ')}
                      </span>
                    )}
                    {linkedHere && (
                      here.is_primary
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
