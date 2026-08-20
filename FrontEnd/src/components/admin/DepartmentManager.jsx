import { useState, useEffect, useMemo } from 'react'
import {
  fetchDeptTree,
  createCollege, updateCollege, deleteCollege,
  createDivision, updateDivision, deleteDivision,
  createDepartment, updateDepartment, deleteDepartment,
} from '../../api/admins/departments'

const TEAL = 'var(--brand)'

const ENTITY_LABEL = { college: '단과대학', division: '학부', department: '학과' }

const inputCls = 'w-full text-sm text-(--text) border border-(--border) rounded-lg bg-(--surface-card) outline-none focus:border-(--brand)'
const labelCls = 'text-xs font-bold text-(--text-muted)'

function aliasesToText(arr) { return (arr || []).join(', ') }
function textToAliases(t) {
  return (t || '').split(/[,\n]/).map((x) => x.trim()).filter(Boolean)
}

export default function DepartmentManager() {
  const [tree, setTree] = useState(null)
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState(null)               // { type, text }
  const [collapsed, setCollapsed] = useState({})     // { [collegeId]: true } — 접힌 단과대
  // 편집 모달: { entity, mode: 'add'|'edit', data } / null
  const [modal, setModal] = useState(null)
  const [modalErr, setModalErr] = useState(null)
  const [saving, setSaving] = useState(false)

  async function load() {
    try { setTree(await fetchDeptTree()) }
    catch (e) { setMsg({ type: 'error', text: e.message }) }
  }
  useEffect(() => { (async () => { setLoading(true); await load(); setLoading(false) })() }, [])

  const colleges = tree?.colleges || []
  const unassigned = tree?.unassigned || []
  // 학과 모달의 학부 선택지 — 선택된 단과대에 속한 학부
  const modalDivisions = useMemo(() => {
    if (modal?.entity !== 'department') return []
    const c = colleges.find((x) => x.id === Number(modal.data.college_id))
    return c ? c.divisions : []
  }, [modal, colleges])

  const totalDepts = useMemo(() => {
    let n = unassigned.length
    for (const c of colleges) { n += c.departments.length; for (const dv of c.divisions) n += dv.departments.length }
    return n
  }, [colleges, unassigned])

  function toggle(cid) { setCollapsed((p) => ({ ...p, [cid]: !p[cid] })) }

  // ── 모달 열기 ──
  const openCollege = (mode, data = {}) => { setModalErr(null); setModal({ entity: 'college', mode, data: { name: '', ...data } }) }
  const openDivision = (mode, data = {}) => { setModalErr(null); setModal({ entity: 'division', mode, data: { name: '', college_id: '', ...data } }) }
  const openDepartment = (mode, data = {}) => {
    setModalErr(null)
    setModal({
      entity: 'department', mode,
      data: { name: '', college_id: '', division_id: '', aliases: '', homepage_url: '', phone: '', ...data },
    })
  }
  const setD = (k, v) => setModal((m) => ({ ...m, data: { ...m.data, [k]: v } }))

  async function saveModal() {
    const m = modal
    if (!m.data.name?.trim()) { setModalErr(`${ENTITY_LABEL[m.entity]} 이름을 입력하세요.`); return }
    setSaving(true); setModalErr(null)
    try {
      let doneMsg = `${ENTITY_LABEL[m.entity]} 정보를 저장했어요.`
      if (m.entity === 'college') {
        if (m.mode === 'add') await createCollege(m.data.name)
        else await updateCollege(m.data.id, m.data.name)
      } else if (m.entity === 'division') {
        if (!m.data.college_id) { setModalErr('소속 단과대학을 선택하세요.'); setSaving(false); return }
        const payload = { name: m.data.name, college_id: Number(m.data.college_id) }
        if (m.mode === 'add') await createDivision(payload)
        else await updateDivision(m.data.id, payload)
      } else {
        const payload = {
          name: m.data.name,
          college_id: m.data.college_id ? Number(m.data.college_id) : null,
          division_id: m.data.division_id ? Number(m.data.division_id) : null,
          aliases: textToAliases(m.data.aliases),
          homepage_url: m.data.homepage_url || null,
          phone: m.data.phone || null,
        }
        if (m.mode === 'add') { await createDepartment(payload) }
        else {
          const res = await updateDepartment(m.data.id, payload)
          if (res?.renamed_scholarships) doneMsg = `저장했어요. 이름 변경에 맞춰 장학금 ${res.renamed_scholarships}건의 '대상 학과'도 함께 수정했어요.`
        }
      }
      setModal(null)
      setMsg({ type: 'success', text: doneMsg })
      await load()
    } catch (e) {
      setModalErr(e.message)
    } finally { setSaving(false) }
  }

  async function removeCollege(c) {
    if (!confirm(`'${c.name}' 단과대학을 삭제할까요?`)) return
    try { await deleteCollege(c.id); setMsg({ type: 'success', text: '삭제했어요.' }); await load() }
    catch (e) { setMsg({ type: 'error', text: e.message }) }
  }
  async function removeDivision(dv) {
    if (!confirm(`'${dv.name}' 학부를 삭제할까요?`)) return
    try { await deleteDivision(dv.id); setMsg({ type: 'success', text: '삭제했어요.' }); await load() }
    catch (e) { setMsg({ type: 'error', text: e.message }) }
  }
  async function removeDepartment(d) {
    if (!confirm(`'${d.name}' 학과를 삭제할까요?`)) return
    try { await deleteDepartment(d.id); setMsg({ type: 'success', text: '삭제했어요.' }); await load() }
    catch (e) { setMsg({ type: 'error', text: e.message }) }
  }

  // ── 학과 한 줄 ──
  function DeptRow({ d }) {
    return (
      <div className="flex items-center gap-2 border-b border-(--border) last:border-b-0 hover:bg-(--surface-2) transition" style={{ padding: '8px 12px' }}>
        <span className="text-sm font-medium text-(--text)">{d.name}</span>
        {d.aliases?.length > 0 && (
          <span className="text-[11px] text-(--text-faint) truncate" style={{ maxWidth: '220px' }} title={d.aliases.join(', ')}>
            별칭: {d.aliases.join(', ')}
          </span>
        )}
        {d.student_count > 0 && (
          <span className="text-[10px] font-semibold text-(--text-muted) bg-(--surface-2) rounded-full shrink-0" style={{ padding: '1px 7px' }}>학생 {d.student_count}</span>
        )}
        {d.homepage_url && (
          <a href={d.homepage_url} target="_blank" rel="noreferrer" className="shrink-0 text-(--text-faint) hover:text-(--brand) transition" title={d.homepage_url} aria-label="홈페이지">
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}><path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" /></svg>
          </a>
        )}
        {d.phone && <span className="text-[11px] text-(--text-faint) shrink-0 hidden sm:inline">📞 {d.phone}</span>}
        <div className="flex-1" />
        <button onClick={() => openDepartment('edit', { id: d.id, name: d.name, college_id: d.college_id ?? '', division_id: d.division_id ?? '', aliases: aliasesToText(d.aliases), homepage_url: d.homepage_url || '', phone: d.phone || '' })}
          className="text-xs font-semibold text-(--brand) hover:underline shrink-0">수정</button>
        <button onClick={() => removeDepartment(d)} className="text-xs font-semibold text-red-500 hover:underline shrink-0">삭제</button>
      </div>
    )
  }

  const addBtnCls = 'inline-flex items-center gap-1 text-[11px] font-bold rounded-lg border transition'
  const plusIcon = <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.4}><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>

  return (
    <div className="flex-1 bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) flex flex-col" style={{ padding: '32px', gap: '16px' }}>
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-black text-(--text)">학과 관리</h2>
          <p className="text-xs text-(--text-faint) mt-0.5">단과대학·학부·학과를 관리해요. 여기서 바꾸면 코파일럿 <b>학과 소개</b>와 장학금 <b>대상 학과</b>에 바로 반영됩니다.</p>
        </div>
        <button onClick={() => openCollege('add')} className="flex items-center bg-(--brand) text-white text-sm font-bold hover:bg-(--brand-hover) transition rounded-xl" style={{ gap: '6px', padding: '9px 16px' }}>
          {plusIcon}단과대학 추가
        </button>
      </div>

      {msg && <div className={`text-xs font-medium px-4 py-2 rounded-xl ${msg.type === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`}>{msg.text}</div>}

      {loading ? (
        <p className="text-center text-(--text-faint) text-sm" style={{ padding: '40px' }}>불러오는 중…</p>
      ) : (
        <div className="flex-1 overflow-y-auto flex flex-col" style={{ gap: '14px' }}>
          <p className="text-[11px] text-(--text-faint)">단과대학 {colleges.length} · 학과 {totalDepts}</p>

          {colleges.map((c) => {
            const open = !collapsed[c.id]
            return (
              <div key={c.id} className="border border-(--border) rounded-xl overflow-hidden">
                {/* 단과대학 헤더 */}
                <div className="flex items-center gap-2 bg-(--surface-2)" style={{ padding: '10px 12px' }}>
                  <button onClick={() => toggle(c.id)} className="text-(--text-faint) hover:text-(--text-body) shrink-0" aria-label="펼치기/접기">
                    <svg className={`h-4 w-4 transition-transform ${open ? '' : '-rotate-90'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" /></svg>
                  </button>
                  <span className="text-sm font-black text-(--text)">{c.name}</span>
                  <span className="text-[11px] text-(--text-faint)">학부 {c.divisions.length} · 직속학과 {c.departments.length}</span>
                  <div className="flex-1" />
                  <button onClick={() => openDivision('add', { college_id: c.id })} className={addBtnCls + ' text-(--brand) border-(--brand-a20) hover:bg-(--brand-tint)'} style={{ padding: '4px 9px' }}>{plusIcon}학부</button>
                  <button onClick={() => openDepartment('add', { college_id: c.id })} className={addBtnCls + ' text-(--brand) border-(--brand-a20) hover:bg-(--brand-tint)'} style={{ padding: '4px 9px' }}>{plusIcon}학과</button>
                  <button onClick={() => openCollege('edit', { id: c.id, name: c.name })} className="text-xs font-semibold text-(--text-muted) hover:text-(--brand) shrink-0" style={{ marginLeft: '4px' }}>수정</button>
                  <button onClick={() => removeCollege(c)} className="text-xs font-semibold text-red-500 hover:underline shrink-0">삭제</button>
                </div>

                {open && (
                  <div style={{ padding: '4px 0' }}>
                    {/* 학부들 */}
                    {c.divisions.map((dv) => (
                      <div key={dv.id} style={{ padding: '2px 0 2px 14px' }}>
                        <div className="flex items-center gap-2" style={{ padding: '6px 12px 6px 0' }}>
                          <span className="text-[10px] font-bold text-white rounded-full shrink-0" style={{ padding: '1px 7px', background: '#0ea5a0' }}>학부</span>
                          <span className="text-sm font-bold text-(--text-body)">{dv.name}</span>
                          <span className="text-[11px] text-(--text-faint)">학과 {dv.departments.length}</span>
                          <div className="flex-1" />
                          <button onClick={() => openDepartment('add', { college_id: c.id, division_id: dv.id })} className={addBtnCls + ' text-(--brand) border-(--brand-a20) hover:bg-(--brand-tint)'} style={{ padding: '3px 8px' }}>{plusIcon}학과</button>
                          <button onClick={() => openDivision('edit', { id: dv.id, name: dv.name, college_id: c.id })} className="text-xs font-semibold text-(--text-muted) hover:text-(--brand) shrink-0">수정</button>
                          <button onClick={() => removeDivision(dv)} className="text-xs font-semibold text-red-500 hover:underline shrink-0">삭제</button>
                        </div>
                        {dv.departments.length > 0 && (
                          <div className="border-l-2 border-(--border) rounded-bl-lg" style={{ marginLeft: '10px' }}>
                            {dv.departments.map((d) => <DeptRow key={d.id} d={d} />)}
                          </div>
                        )}
                      </div>
                    ))}

                    {/* 학부 없는 직속 학과 */}
                    {c.departments.length > 0 && (
                      <div style={{ padding: '2px 0 2px 14px' }}>
                        {c.divisions.length > 0 && <p className="text-[11px] font-semibold text-(--text-faint)" style={{ padding: '4px 0' }}>학부 미소속 (단과대 직속)</p>}
                        <div className="border-l-2 border-(--border) rounded-bl-lg" style={{ marginLeft: '10px' }}>
                          {c.departments.map((d) => <DeptRow key={d.id} d={d} />)}
                        </div>
                      </div>
                    )}

                    {c.divisions.length === 0 && c.departments.length === 0 && (
                      <p className="text-[11px] text-(--text-faint)" style={{ padding: '8px 20px' }}>학부·학과가 없습니다. 위 <b>+학부</b> / <b>+학과</b>로 추가하세요.</p>
                    )}
                  </div>
                )}
              </div>
            )
          })}

          {/* 소속 미지정 학과 */}
          {unassigned.length > 0 && (
            <div className="border border-dashed border-(--border) rounded-xl overflow-hidden">
              <div className="flex items-center gap-2 bg-(--surface-2)" style={{ padding: '10px 12px' }}>
                <span className="text-sm font-black text-(--text-muted)">소속 미지정 학과</span>
              </div>
              <div>{unassigned.map((d) => <DeptRow key={d.id} d={d} />)}</div>
            </div>
          )}
        </div>
      )}

      {/* ─────────────── 편집 모달 ─────────────── */}
      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.45)' }} onMouseDown={() => setModal(null)}>
          <div className="bg-(--surface-card) rounded-2xl shadow-xl border border-(--border) w-full" style={{ maxWidth: '460px', margin: '20px', maxHeight: '88vh', overflowY: 'auto' }} onMouseDown={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-(--border)" style={{ padding: '16px 20px' }}>
              <h3 className="text-sm font-black text-(--text)">{ENTITY_LABEL[modal.entity]} {modal.mode === 'add' ? '추가' : '수정'}</h3>
              <button onClick={() => setModal(null)} className="text-(--text-faint) hover:text-(--text-body)" aria-label="닫기">✕</button>
            </div>

            <div className="flex flex-col" style={{ padding: '20px', gap: '14px' }}>
              {modalErr && <div className="text-xs font-medium bg-red-50 text-red-600 rounded-xl" style={{ padding: '8px 12px' }}>{modalErr}</div>}

              <label className="flex flex-col gap-1">
                <span className={labelCls}>{ENTITY_LABEL[modal.entity]} 이름 *</span>
                <input className={inputCls} style={{ padding: '8px 10px' }} value={modal.data.name} onChange={(e) => setD('name', e.target.value)} autoFocus
                  placeholder={modal.entity === 'college' ? '예: 소프트웨어(SW)융합대학' : modal.entity === 'division' ? '예: 소프트웨어학부' : '예: 컴퓨터공학전공'} />
              </label>

              {modal.entity === 'division' && (
                <label className="flex flex-col gap-1">
                  <span className={labelCls}>소속 단과대학 *</span>
                  <select className={inputCls} style={{ padding: '8px 10px' }} value={modal.data.college_id} onChange={(e) => setD('college_id', e.target.value)}>
                    <option value="">선택하세요</option>
                    {colleges.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                  </select>
                </label>
              )}

              {modal.entity === 'department' && (
                <>
                  <div className="grid grid-cols-2" style={{ gap: '12px' }}>
                    <label className="flex flex-col gap-1">
                      <span className={labelCls}>소속 단과대학</span>
                      <select className={inputCls} style={{ padding: '8px 10px' }} value={modal.data.college_id}
                        onChange={(e) => { setD('college_id', e.target.value); setD('division_id', '') }}>
                        <option value="">미지정</option>
                        {colleges.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                      </select>
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className={labelCls}>소속 학부 <span className="font-normal text-(--text-faint)">(없으면 직속)</span></span>
                      <select className={inputCls} style={{ padding: '8px 10px' }} value={modal.data.division_id}
                        onChange={(e) => setD('division_id', e.target.value)} disabled={!modal.data.college_id}>
                        <option value="">없음 (직속)</option>
                        {modalDivisions.map((dv) => <option key={dv.id} value={dv.id}>{dv.name}</option>)}
                      </select>
                    </label>
                  </div>
                  <label className="flex flex-col gap-1">
                    <span className={labelCls}>별칭·약칭 <span className="font-normal text-(--text-faint)">(쉼표로 구분 · 코파일럿 검색용, 예: 컴공, 컴퓨터공학)</span></span>
                    <textarea className={inputCls} style={{ padding: '8px 10px', minHeight: '54px', resize: 'vertical' }} value={modal.data.aliases} onChange={(e) => setD('aliases', e.target.value)} placeholder="컴공, 컴퓨터공학" />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className={labelCls}>홈페이지 URL</span>
                    <input className={inputCls} style={{ padding: '8px 10px' }} value={modal.data.homepage_url} onChange={(e) => setD('homepage_url', e.target.value)} placeholder="https://cs.wsu.ac.kr/main/index.jsp" />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className={labelCls}>학과 사무실 전화 <span className="font-normal text-(--text-faint)">(여러 개면 쉼표)</span></span>
                    <input className={inputCls} style={{ padding: '8px 10px' }} value={modal.data.phone} onChange={(e) => setD('phone', e.target.value)} placeholder="042-630-9710" />
                  </label>
                </>
              )}
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-(--border)" style={{ padding: '14px 20px' }}>
              <button onClick={() => setModal(null)} className="text-sm font-semibold text-(--text-muted) hover:text-(--text-body) rounded-lg" style={{ padding: '8px 14px' }}>취소</button>
              <button onClick={saveModal} disabled={saving} className="bg-(--brand) text-white text-sm font-bold hover:bg-(--brand-hover) transition disabled:opacity-50 rounded-lg" style={{ padding: '8px 18px' }}>
                {saving ? '저장 중…' : '저장'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
