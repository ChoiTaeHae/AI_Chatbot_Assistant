import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { fetchCourses, previewCourses, commitCourses, addCourse, deleteCourse } from '../../api/me'
import useIsMobile from '../../hooks/useIsMobile'

/* 수강 이력 — 포털의 '전체 기이수성적' 엑셀을 올려 채운다.
 *
 * 업로드가 미리보기 → 확정 2단계인 이유
 *   성적표는 민감한 데이터라, 형식이 다른 파일을 올렸을 때 곧바로 DB에 들어가면 되돌리기가
 *   번거롭다. 몇 과목이 새로 들어가고 몇 개가 이미 있는지 보고 나서 저장하게 한다.
 *
 * 병합 방식이라 같은 파일을 다시 올려도 중복이 생기지 않는다
 *   (학번, 과목번호, 년도, 학기)가 같으면 서버가 건너뛴다. 재수강은 학기가 달라 따로 남는다.
 *
 * 여백은 전역 `* { padding: 0 }` 리셋이 Tailwind 유틸을 덮어써서 인라인 style로 준다.
 */

const EMPTY_MANUAL = {
  year: '', semester: '1학기', course_code: '', course_name: '',
  category: '전공선택', credits: '', grade: '', grade_point: '',
}
const CATEGORIES = ['전공필수', '전공선택', '교양필수', '교양선택', '일반', '트랙']
const SEMESTERS = ['1학기', '2학기', '여름학기', '겨울학기']
// 학기 시간순 가중치. 문자열 정렬로는 '여름학기'가 '2학기'보다 앞서 버려 학기 순서가 뒤집힌다.
const TERM_ORDER = { '1학기': 1, '여름학기': 2, '2학기': 3, '겨울학기': 4 }
const ALL = '__all__'
// 목록 스크롤 높이 — 한 줄 약 52px 기준 6.5줄. 소수로 잘라 '더 있다'는 게 보이게 한다.
const LIST_MAX_HEIGHT = 338

export default function CourseSection({ onGpaChange }) {
  const isMobile = useIsMobile()
  const fileRef = useRef(null)

  const [courses, setCourses] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [msg, setMsg] = useState(null)

  const [preview, setPreview] = useState(null)    // { rows, total, new_count, ... }
  const [uploading, setUploading] = useState(false)
  const [committing, setCommitting] = useState(false)

  const [manualOpen, setManualOpen] = useState(false)
  const [manual, setManual] = useState(EMPTY_MANUAL)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [term, setTerm] = useState(ALL)          // 학기 필터 ('__all__' = 전체)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setCourses(await fetchCourses())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  function flash(text) {
    setMsg(text)
    setTimeout(() => setMsg(null), 4000)
  }

  async function onPickFile(e) {
    const file = e.target.files?.[0]
    e.target.value = ''                            // 같은 파일 다시 고를 수 있게 초기화
    if (!file) return
    setUploading(true); setError(null)
    try {
      setPreview(await previewCourses(file))
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
    }
  }

  async function commit() {
    setCommitting(true); setError(null)
    try {
      const r = await commitCourses(preview.rows)
      setPreview(null)
      await load()
      onGpaChange?.(r.gpa)
      flash(`${r.added}과목을 추가했습니다. (이미 있던 ${r.skipped}과목은 건너뜀)`)
    } catch (e) {
      setError(e.message)
    } finally {
      setCommitting(false)
    }
  }

  async function submitManual() {
    setError(null)
    if (!manual.course_code.trim() || !manual.course_name.trim()) {
      setError('과목번호와 과목명을 입력하세요.'); return
    }
    try {
      const r = await addCourse({
        ...manual,
        year: manual.year === '' ? null : Number(manual.year),
        credits: manual.credits === '' ? 0 : Number(manual.credits),
        grade_point: manual.grade_point === '' ? null : Number(manual.grade_point),
        is_passed: true,
      })
      setManual(EMPTY_MANUAL)
      setManualOpen(false)
      await load()
      onGpaChange?.(r.gpa)
      flash('과목을 추가했습니다.')
    } catch (e) {
      setError(e.message)
    }
  }

  async function confirmDelete() {
    const target = deleteTarget
    setDeleteTarget(null)
    try {
      const r = await deleteCourse(target.id)
      await load()
      onGpaChange?.(r.gpa)
      flash('과목을 삭제했습니다.')
    } catch (e) {
      setError(e.message)
    }
  }

  // 학기별 묶음 — 최신 학기가 위로. 정렬은 (년도, 학기가중치) 내림차순으로 한다.
  const allGroups = useMemo(() => {
    const map = new Map()
    for (const c of courses) {
      const key = c.year ? `${c.year} ${c.semester || ''}`.trim() : '학기 미상'
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(c)
    }
    const rank = (list) => {
      const c = list[0]
      return (c.year || 0) * 10 + (TERM_ORDER[c.semester] || 0)
    }
    return [...map.entries()].sort((a, b) => rank(b[1]) - rank(a[1]))
  }, [courses])

  // 드롭다운에 보여줄 학기 목록 (과목 수 포함)
  const termOptions = useMemo(
    () => allGroups.map(([key, list]) => ({ key, count: list.length })), [allGroups])

  const grouped = useMemo(
    () => (term === ALL ? allGroups : allGroups.filter(([key]) => key === term)),
    [allGroups, term])

  // 선택한 학기가 사라지면(마지막 과목 삭제 등) 전체로 되돌린다
  useEffect(() => {
    if (term !== ALL && !allGroups.some(([key]) => key === term)) setTerm(ALL)
  }, [allGroups, term])

  const totalCredits = courses.filter((c) => c.is_passed).reduce((n, c) => n + (c.credits || 0), 0)

  const cardCls = 'bg-(--surface-card) rounded-2xl shadow-sm border border-(--border)'
  const cardStyle = { padding: isMobile ? '18px 16px' : '24px 26px' }
  const inputCls = 'w-full border border-(--border) rounded-xl text-(--text) bg-(--surface-card) outline-none focus:border-(--brand) transition'
  const inputStyle = { padding: '10px 12px', fontSize: isMobile ? '16px' : '14px' }
  const labelCls = 'text-xs font-bold text-(--text-muted)'

  return (
    <section className={cardCls} style={{ ...cardStyle, marginBottom: '16px' }}>
      <div className="flex items-start flex-wrap" style={{ gap: '10px' }}>
        <div className="flex-1 min-w-0">
          <h2 className="font-black text-(--text)" style={{ fontSize: '15px' }}>수강 이력</h2>
          <p className="text-[11px] text-(--text-faint)" style={{ marginTop: '4px', lineHeight: 1.6 }}>
            학교 포털의 <b>전체 기이수성적</b> 엑셀을 올리면 과목·학점·평점평균이 자동으로 채워집니다.
          </p>
        </div>
        <div className="flex shrink-0" style={{ gap: '8px' }}>
          <button onClick={() => setManualOpen(true)}
                  className="border border-(--border) rounded-xl text-xs font-bold text-(--text-muted) hover:bg-(--surface-2) transition"
                  style={{ padding: '9px 13px' }}>직접 추가</button>
          <button onClick={() => fileRef.current?.click()} disabled={uploading}
                  className="bg-(--brand) text-white rounded-xl text-sm font-black hover:bg-(--brand-hover) transition disabled:opacity-50"
                  style={{ padding: '9px 16px' }}>
            {uploading ? '읽는 중…' : '엑셀 올리기'}
          </button>
          <input ref={fileRef} type="file" accept=".xlsx,.xlsm" onChange={onPickFile} style={{ display: 'none' }} />
        </div>
      </div>

      {error && <p className="text-xs font-bold text-red-500" style={{ marginTop: '12px' }}>{error}</p>}
      {msg && <p className="text-xs font-bold text-(--brand)" style={{ marginTop: '12px' }}>{msg}</p>}

      {/* 요약 + 학기 필터 */}
      {!loading && courses.length > 0 && (
        <div className="flex flex-wrap items-center rounded-xl bg-(--surface-2)"
             style={{ gap: '12px', padding: '12px 14px', marginTop: '14px' }}>
          <span className="text-xs text-(--text-muted)">이수 과목 <b className="text-(--text)">{courses.length}</b></span>
          <span className="text-xs text-(--text-muted)">이수 학점 <b className="text-(--text)">{totalCredits}</b></span>
          <span className="flex-1" />
          <select value={term} onChange={(e) => setTerm(e.target.value)}
                  className="border border-(--border) rounded-lg bg-(--surface-card) text-(--text-muted) outline-none cursor-pointer hover:border-(--brand-a40) transition"
                  style={{ padding: '6px 9px', fontSize: isMobile ? '16px' : '12.5px' }}
                  aria-label="학기 선택">
            <option value={ALL}>전체 ({courses.length}과목)</option>
            {termOptions.map((o) => (
              <option key={o.key} value={o.key}>{o.key} ({o.count}과목)</option>
            ))}
          </select>
        </div>
      )}

      {/* 목록 — 과목이 30개를 넘기도 해서 페이지를 밀지 않도록 자체 스크롤 영역에 담는다.
          overscrollBehavior: 목록 끝에서 페이지가 따라 밀리는 것을 막는다(중첩 스크롤). */}
      <div style={{
        marginTop: '14px',
        maxHeight: courses.length > 0 ? `${LIST_MAX_HEIGHT}px` : undefined,
        overflowY: courses.length > 0 ? 'auto' : undefined,
        overscrollBehavior: 'contain',
      }}>
        {loading && <p className="text-xs text-(--text-faint) text-center" style={{ padding: '24px' }}>불러오는 중…</p>}
        {!loading && courses.length === 0 && (
          <p className="text-xs text-(--text-faint) text-center" style={{ padding: '28px', lineHeight: 1.7 }}>
            등록된 수강 이력이 없습니다.<br />엑셀을 올리거나 직접 추가해 주세요.
          </p>
        )}

        {grouped.map(([termKey, list]) => (
          <div key={termKey} style={{ marginBottom: '14px' }}>
            {/* 스크롤해도 지금 보고 있는 학기가 보이도록 상단에 고정.
                배경을 카드색으로 채우지 않으면 아래 항목이 글자에 겹쳐 지나간다. */}
            <p className="font-bold text-(--brand)"
               style={{
                 fontSize: '12.5px', padding: '4px 0 6px',
                 position: 'sticky', top: 0, zIndex: 1, background: 'var(--surface-card)',
               }}>
              {termKey} <span className="font-normal text-(--text-faint)">· {list.length}과목</span>
            </p>
            {list.map((c) => (
              <div key={c.id}
                   className="flex items-center border-b border-(--border)"
                   style={{ gap: '10px', padding: '9px 2px' }}>
                <div className="flex-1 min-w-0">
                  <p className="text-(--text) truncate" style={{ fontSize: '13.5px' }}>{c.course_name}</p>
                  <p className="text-[11px] text-(--text-faint)" style={{ marginTop: '2px' }}>
                    {c.category || '-'} · {c.credits}학점{c.grade ? ` · ${c.grade}` : ''}
                  </p>
                </div>
                <button onClick={() => setDeleteTarget(c)}
                        className="shrink-0 text-(--text-faint) hover:text-red-500 transition"
                        aria-label={`${c.course_name} 삭제`} style={{ fontSize: '13px', padding: '4px 6px' }}>✕</button>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* 미리보기 모달 */}
      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
             style={{ background: 'rgba(15,23,42,.5)', padding: isMobile ? '0' : '16px' }}
             onMouseDown={() => !committing && setPreview(null)}>
          <div className={`bg-(--surface-card) shadow-xl w-full flex flex-col ${isMobile ? '' : 'rounded-2xl border border-(--border)'}`}
               style={{ maxWidth: isMobile ? 'none' : '620px', height: isMobile ? '100%' : 'auto', maxHeight: isMobile ? '100%' : '86vh' }}
               onMouseDown={(e) => e.stopPropagation()}>
            <div className="border-b border-(--border) shrink-0" style={{ padding: '18px 20px' }}>
              <h3 className="font-black text-(--text)" style={{ fontSize: '15px' }}>업로드 내용 확인</h3>
              <p className="text-xs text-(--text-muted)" style={{ marginTop: '6px', lineHeight: 1.7 }}>
                총 <b>{preview.total}</b>과목 중 <b className="text-(--brand)">{preview.new_count}</b>과목이 새로 추가됩니다.
                {preview.duplicate_count > 0 && <> 이미 등록된 <b>{preview.duplicate_count}</b>과목은 건너뜁니다.</>}
                <br />이수 학점 <b>{preview.total_credits}</b>
                {preview.gpa_preview != null && <> · 이 파일 기준 평점평균 <b>{preview.gpa_preview}</b></>}
              </p>
            </div>

            <div className="overflow-y-auto flex-1" style={{ padding: '10px 20px' }}>
              {preview.rows.map((r, i) => (
                <div key={`${r.course_code}-${r.year}-${r.semester}-${i}`}
                     className="flex items-center border-b border-(--border)"
                     style={{ gap: '10px', padding: '8px 0' }}>
                  <div className="flex-1 min-w-0">
                    <p className="text-(--text) truncate" style={{ fontSize: '13px' }}>{r.course_name}</p>
                    <p className="text-[11px] text-(--text-faint)" style={{ marginTop: '2px' }}>
                      {r.year} {r.semester} · {r.raw_category}
                      {r.raw_category !== r.category && <span className="text-(--text-faint)"> → {r.category}</span>}
                      {' · '}{r.credits}학점{r.grade ? ` · ${r.grade}` : ''}
                    </p>
                  </div>
                </div>
              ))}
            </div>

            <div className="border-t border-(--border) flex shrink-0" style={{ gap: '8px', padding: '14px 20px' }}>
              <button onClick={() => setPreview(null)} disabled={committing}
                      className="flex-1 border border-(--border) rounded-xl text-sm font-bold text-(--text-muted) hover:bg-(--surface-2) transition disabled:opacity-50"
                      style={{ padding: '12px' }}>취소</button>
              <button onClick={commit} disabled={committing || preview.new_count === 0}
                      className="flex-1 bg-(--brand) text-white rounded-xl text-sm font-black hover:bg-(--brand-hover) transition disabled:opacity-40"
                      style={{ padding: '12px' }}>
                {committing ? '저장 중…' : preview.new_count === 0 ? '추가할 과목 없음' : `${preview.new_count}과목 저장`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 직접 추가 모달 */}
      {manualOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center"
             style={{ background: 'rgba(15,23,42,.5)', padding: '16px' }}
             onMouseDown={() => setManualOpen(false)}>
          <div className="bg-(--surface-card) rounded-2xl shadow-xl border border-(--border) w-full"
               style={{ maxWidth: '480px', maxHeight: '88vh', overflowY: 'auto' }}
               onMouseDown={(e) => e.stopPropagation()}>
            <div className="border-b border-(--border)" style={{ padding: '18px 20px' }}>
              <h3 className="font-black text-(--text)" style={{ fontSize: '15px' }}>과목 직접 추가</h3>
              <p className="text-[11px] text-(--text-faint)" style={{ marginTop: '4px' }}>
                엑셀에 없는 과목(교환학생·인정과목 등)을 넣을 때 사용하세요.
              </p>
            </div>
            <div style={{ padding: '18px 20px' }}>
              <div className="grid grid-cols-2" style={{ gap: '12px' }}>
                <label className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>년도</span>
                  <input type="number" placeholder="2026" className={inputCls} style={inputStyle}
                         value={manual.year} onChange={(e) => setManual({ ...manual, year: e.target.value })} />
                </label>
                <label className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>학기</span>
                  <select className={inputCls} style={inputStyle}
                          value={manual.semester} onChange={(e) => setManual({ ...manual, semester: e.target.value })}>
                    {SEMESTERS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </label>
                <label className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>과목번호</span>
                  <input className={inputCls} style={inputStyle} placeholder="0001234"
                         value={manual.course_code} onChange={(e) => setManual({ ...manual, course_code: e.target.value })} />
                </label>
                <label className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>이수구분</span>
                  <select className={inputCls} style={inputStyle}
                          value={manual.category} onChange={(e) => setManual({ ...manual, category: e.target.value })}>
                    {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </label>
              </div>
              <label className="flex flex-col" style={{ gap: '5px', marginTop: '12px' }}>
                <span className={labelCls}>과목명</span>
                <input className={inputCls} style={inputStyle} placeholder="예: 자료구조"
                       value={manual.course_name} onChange={(e) => setManual({ ...manual, course_name: e.target.value })} />
              </label>
              <div className="grid grid-cols-3" style={{ gap: '12px', marginTop: '12px' }}>
                <label className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>학점</span>
                  <input type="number" min="0" step="1" className={inputCls} style={inputStyle}
                         value={manual.credits} onChange={(e) => setManual({ ...manual, credits: e.target.value })} />
                </label>
                <label className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>등급</span>
                  <input className={inputCls} style={inputStyle} placeholder="A+"
                         value={manual.grade} onChange={(e) => setManual({ ...manual, grade: e.target.value })} />
                </label>
                <label className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>평점</span>
                  <input type="number" min="0" max="4.5" step="0.1" className={inputCls} style={inputStyle}
                         placeholder="4.5"
                         value={manual.grade_point} onChange={(e) => setManual({ ...manual, grade_point: e.target.value })} />
                </label>
              </div>
              <p className="text-[11px] text-(--text-faint)" style={{ marginTop: '8px', lineHeight: 1.6 }}>
                P(Pass) 과목처럼 평점이 없으면 평점 칸을 비워두세요 — 평점평균 계산에서 빠집니다.
              </p>
            </div>
            <div className="border-t border-(--border) flex" style={{ gap: '8px', padding: '14px 20px' }}>
              <button onClick={() => { setManualOpen(false); setManual(EMPTY_MANUAL) }}
                      className="flex-1 border border-(--border) rounded-xl text-sm font-bold text-(--text-muted) hover:bg-(--surface-2) transition"
                      style={{ padding: '12px' }}>취소</button>
              <button onClick={submitManual}
                      className="flex-1 bg-(--brand) text-white rounded-xl text-sm font-black hover:bg-(--brand-hover) transition"
                      style={{ padding: '12px' }}>추가</button>
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
               style={{ maxWidth: '380px' }} onMouseDown={(e) => e.stopPropagation()}>
            <div style={{ padding: '20px 22px 16px' }}>
              <p className="font-black text-(--text)" style={{ fontSize: '14px' }}>이 과목을 삭제할까요?</p>
              <p className="text-xs text-(--text-muted)" style={{ marginTop: '8px' }}>
                {deleteTarget.course_name} · {deleteTarget.credits}학점
              </p>
              <p className="text-[11px] text-(--text-faint)" style={{ marginTop: '8px' }}>
                평점평균과 졸업 현황이 다시 계산됩니다.
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
    </section>
  )
}
