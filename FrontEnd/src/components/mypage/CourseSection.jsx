import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { fetchCourses, previewCourses, commitCourses, addCourse, deleteCourse } from '../../api/me'
import useIsMobile from '../../hooks/useIsMobile'
import Toast from '../common/Toast'

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

// 이수구분 배지 — 전공(티일)·교양(보라)·그 외(무채색)로 계열을 색으로 나눈다.
// 줄임말을 쓰는 이유: 폭을 고정해야 과목명 칸이 학기마다 들쭉날쭉하지 않는다.
const CATEGORY_BADGE = {
  전공필수: { short: '전필', bg: 'var(--brand-a20)', color: 'var(--brand)' },
  전공선택: { short: '전선', bg: 'var(--brand-a8)', color: 'var(--brand)' },
  교양필수: { short: '교필', bg: 'var(--accent-tint)', color: 'var(--accent)' },
  교양선택: { short: '교선', bg: 'var(--accent-tint)', color: 'var(--accent)' },
  트랙: { short: '트랙', bg: 'var(--amber-tint)', color: 'var(--amber-text)' },
}
const DEFAULT_BADGE = { short: '일반', bg: 'var(--surface-2)', color: 'var(--text-muted)' }

/* 성적 색 — P(Pass)는 평점에 안 들어가므로 흐리게 빼고, A는 눈에 띄게, F는 경고색.
   나머지(B·C·D)는 본문색 그대로 둔다. 전부 색을 칠하면 도로 알록달록해진다. */
function gradeTone(g) {
  if (!g || g === 'P') return 'var(--text-faint)'
  if (g.startsWith('A')) return 'var(--brand)'
  if (g.startsWith('F')) return 'var(--danger-text)'
  return 'var(--text-body)'
}
// 학기 시간순 가중치. 문자열 정렬로는 '여름학기'가 '2학기'보다 앞서 버려 학기 순서가 뒤집힌다.
const TERM_ORDER = { '1학기': 1, '여름학기': 2, '2학기': 3, '겨울학기': 4 }

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
  // 펼친 학기 집합. null이면 '아직 손대지 않음' → 최신 학기만 펼친 기본값을 쓴다.
  // (기본값을 state 초기값으로 넣지 않는 이유: 과목을 불러오기 전에는 학기 목록을 모른다)
  const [openTerms, setOpenTerms] = useState(null)

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

  // 기본은 최신 학기 하나만 펼침 — 40과목 가까이 쌓이면 전부 펼친 목록이 화면 몇 개 분량이라
  // 아래 카드(비밀번호 등)까지 스크롤로만 닿는다. 지난 학기는 필요할 때 열어 본다.
  const defaultOpen = useMemo(
    () => new Set(allGroups.length ? [allGroups[0][0]] : []), [allGroups])
  const open = openTerms ?? defaultOpen
  const allExpanded = allGroups.length > 0 && allGroups.every(([key]) => open.has(key))

  // 이전 값(openTerms)이 아니라 기본값이 반영된 open을 기준으로 바꾼다 —
  // 아직 손대지 않았으면 openTerms는 null이라 갱신 함수의 prev를 쓸 수 없다.
  function toggleTerm(key) {
    const next = new Set(open)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    setOpenTerms(next)
  }

  function toggleAll() {
    setOpenTerms(allExpanded ? new Set() : new Set(allGroups.map(([key]) => key)))
  }

  const passedCredits = (list) => list.filter((c) => c.is_passed)
    .reduce((n, c) => n + (c.credits || 0), 0)
  const totalCredits = passedCredits(courses)

  const cardCls = 'bg-(--surface-card) rounded-2xl shadow-sm border border-(--border)'
  const cardStyle = { padding: isMobile ? '18px 16px' : '24px 26px' }
  const inputCls = 'w-full border border-(--border) rounded-xl text-(--text) bg-(--surface-card) outline-none focus:border-(--brand) transition'
  const inputStyle = { padding: '10px 12px', fontSize: isMobile ? '16px' : '14px' }
  const labelCls = 'text-xs font-bold text-(--text-muted)'

  return (
    <section className={cardCls} style={cardStyle}>
      <div className="flex items-start flex-wrap" style={{ gap: '10px' }}>
        <div className="flex-1 min-w-0">
          <h2 className="font-black text-(--text)" style={{ fontSize: '15px' }}>수강 이력</h2>
          <p className="text-xs text-(--text-faint)" style={{ marginTop: '4px', lineHeight: 1.6 }}>
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

      {/* 오류는 카드 안에 남긴다 — 어떤 동작이 실패했는지 옆에 붙어 있어야 하고 사라지면 안 된다.
          성공 알림만 토스트로 띄운다(나타날 때 아래 목록을 밀지 않도록). */}
      {error && <p className="text-xs font-bold text-red-500" style={{ marginTop: '12px' }}>{error}</p>}
      <Toast message={msg} />

      {/* 요약 + 전체 펼치기 */}
      {!loading && courses.length > 0 && (
        <div className="flex flex-wrap items-center rounded-xl bg-(--surface-2)"
             style={{ gap: '12px', padding: '12px 14px', marginTop: '14px' }}>
          <span className="text-xs text-(--text-muted)">이수 과목 <b className="text-(--text)">{courses.length}</b></span>
          <span className="text-xs text-(--text-muted)">이수 학점 <b className="text-(--text)">{totalCredits}</b></span>
          <span className="text-xs text-(--text-muted)">학기 <b className="text-(--text)">{allGroups.length}</b></span>
          <span className="flex-1" />
          <button type="button" onClick={toggleAll}
                  className="border border-(--border) rounded-lg bg-(--surface-card) text-(--text-muted) font-bold hover:border-(--brand-a40) hover:text-(--text) transition"
                  style={{ padding: '6px 10px', fontSize: '12px' }}>
            {allExpanded ? '모두 접기' : '모두 펼치기'}
          </button>
        </div>
      )}

      {/* 목록 — 전용 탭 안에 있으므로 페이지 스크롤에 그대로 맡긴다.
          예전엔 카드 안에 자체 스크롤 영역을 뒀는데, 페이지 스크롤과 겹쳐 스크롤바가 두 개로
          보이고 목록 끝에서 스크롤이 페이지로 튀는 문제가 있었다.
          길이는 학기별 접기로 줄인다 — 다 펼쳐도 학기 머리글은 sticky라 위치를 잃지 않는다. */}
      <div style={{ marginTop: '14px' }}>
        {/* 스켈레톤 — 들어올 목록과 같은 높이를 미리 잡아 로딩이 끝날 때 화면이 튀지 않는다 */}
        {loading && [0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="flex items-center border-b border-(--border)"
               style={{ gap: '10px', padding: '8px 6px' }}>
            <span className="skeleton shrink-0" style={{ width: '36px', height: '20px' }} />
            <span className="skeleton" style={{ flex: 1, height: '14px', maxWidth: `${190 - i * 22}px` }} />
            <span className="flex-1" />
            <span className="skeleton shrink-0" style={{ width: '34px', height: '12px' }} />
            <span className="skeleton shrink-0" style={{ width: '22px', height: '12px' }} />
          </div>
        ))}
        {!loading && courses.length === 0 && (
          <p className="text-xs text-(--text-faint) text-center" style={{ padding: '28px', lineHeight: 1.7 }}>
            등록된 수강 이력이 없습니다.<br />엑셀을 올리거나 직접 추가해 주세요.
          </p>
        )}

        {allGroups.map(([termKey, list]) => {
          const isOpen = open.has(termKey)
          return (
            <div key={termKey} style={{ marginBottom: '6px' }}>
              {/* 학기 머리글 = 접기 버튼. 스크롤해도 지금 보고 있는 학기가 보이도록 상단에 고정.
                  --sticky-offset: 부모(마이페이지)가 위에 고정 요소를 두면 그 높이만큼 내려 붙는다.
                  단독으로 쓰일 땐 0이라 화면 맨 위에 붙는다.
                  배경은 className으로 준다 — 인라인 style로 주면 hover 클래스가 밀려 안 먹는다. */}
              <button type="button" onClick={() => toggleTerm(termKey)} aria-expanded={isOpen}
                      className="w-full flex items-center text-left rounded-lg bg-(--surface-card) hover:bg-(--surface-2) transition"
                      style={{
                        gap: '7px', padding: '8px 6px',
                        position: 'sticky', top: 'var(--sticky-offset, 0px)', zIndex: 1,
                      }}>
                <svg className="text-(--text-faint) shrink-0" width="12" height="12" viewBox="0 0 24 24"
                     fill="none" stroke="currentColor" strokeWidth={3} aria-hidden="true"
                     style={{ transform: isOpen ? 'none' : 'rotate(-90deg)', transition: 'transform .15s' }}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 9l6 6 6-6" />
                </svg>
                <span className="font-bold text-(--brand)" style={{ fontSize: '13px' }}>{termKey}</span>
                <span className="text-xs text-(--text-faint)">
                  · {list.length}과목 · {passedCredits(list)}학점
                </span>
              </button>

              {/* 한 줄에 [이수구분][과목명][학점][성적][삭제] 순으로 열을 맞춘다.
                  예전엔 셋을 '전공선택 · 3학점 · P'처럼 한 덩어리 회색 글자로 붙여 놨는데,
                  40줄이 똑같은 회색이라 훑을 때 눈이 미끄러졌다. */}
              {isOpen && list.map((c) => {
                const badge = CATEGORY_BADGE[c.category] || DEFAULT_BADGE
                return (
                  <div key={c.id}
                       className="flex items-center border-b border-(--border)"
                       style={{ gap: isMobile ? '8px' : '10px', padding: '8px 6px' }}>
                    <span className="rounded-md font-bold shrink-0 text-center"
                          style={{
                            padding: '3px 0', fontSize: '12px', width: '36px',
                            background: badge.bg, color: badge.color,
                          }}
                          title={c.category || '이수구분 없음'}>
                      {badge.short}
                    </span>
                    <p className="text-(--text) truncate flex-1 min-w-0" style={{ fontSize: '14px' }}>
                      {c.course_name}
                    </p>
                    <span className="text-xs text-(--text-faint) shrink-0">{c.credits}학점</span>
                    {/* 폭을 고정해 성적이 세로로 줄맞춤된다 — 들쭉날쭉하면 비교가 어렵다 */}
                    <span className="font-bold shrink-0 text-right"
                          style={{ fontSize: '13px', width: '26px', color: gradeTone(c.grade) }}>
                      {c.grade || '–'}
                    </span>
                    <button onClick={() => setDeleteTarget(c)}
                            className="shrink-0 text-(--text-faint) hover:text-red-500 transition"
                            aria-label={`${c.course_name} 삭제`} style={{ fontSize: '13px', padding: '4px 6px' }}>✕</button>
                  </div>
                )
              })}
            </div>
          )
        })}
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
                    <p className="text-xs text-(--text-faint)" style={{ marginTop: '2px' }}>
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
              <p className="text-xs text-(--text-faint)" style={{ marginTop: '4px' }}>
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
              <p className="text-xs text-(--text-faint)" style={{ marginTop: '8px', lineHeight: 1.6 }}>
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
              <p className="text-xs text-(--text-faint)" style={{ marginTop: '8px' }}>
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
