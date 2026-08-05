import { useState, useEffect, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchMe, fetchDeptOptions, updateMe, changePassword } from '../api/me'
import { useAuth } from '../store/AuthContext'
import useIsMobile from '../hooks/useIsMobile'
import MascotAvatar from '../components/common/MascotAvatar'
import CourseSection from '../components/mypage/CourseSection'

/* 마이페이지 — 학생이 자기 정보를 고친다.
 *
 * 학년·학점·전공계열을 편집 대상으로 둔 이유
 *   이 값들은 맞춤 장학금 매칭에 그대로 쓰이는데, 실제 성적 시스템 연동이 없어 서버가 학번
 *   기반 더미로 채운다. 학생이 고치지 못하면 매칭이 자기와 무관한 값으로 계산된다.
 *
 * 학번·이름은 신원이라 표시만 한다(서버도 수정을 받지 않는다).
 * 여백은 전역 `* { padding: 0 }` 리셋이 Tailwind 유틸을 덮어써서 인라인 style로 준다.
 */

const MAJOR_FIELDS = ['인문사회', '예술체육', '이공', '의학계열']
const GRADES = [1, 2, 3, 4]

export default function MyPage() {
  const navigate = useNavigate()
  const { user, saveUser } = useAuth()
  const isMobile = useIsMobile()

  const [me, setMe] = useState(null)
  const [depts, setDepts] = useState([])
  const [form, setForm] = useState(null)          // 편집 중인 값
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [msg, setMsg] = useState(null)
  const [interestInput, setInterestInput] = useState('')

  // 비밀번호 변경
  const [pw, setPw] = useState({ current: '', next: '', confirm: '' })
  const [pwSaving, setPwSaving] = useState(false)
  const [pwError, setPwError] = useState(null)
  const [pwMsg, setPwMsg] = useState(null)

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [profile, options] = await Promise.all([fetchMe(), fetchDeptOptions()])
      setMe(profile)
      setDepts(options)
      setForm({
        dept_id: profile.dept_id ?? '',
        grade_year: profile.grade_year ?? '',
        major_field: profile.major_field ?? '',
        interests: profile.interests ?? [],
      })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // 학과 → 계열 자동 채움. 학과 목록에 계열이 실려 오므로 서버를 다시 부르지 않는다.
  function onDeptChange(value) {
    const id = value === '' ? '' : Number(value)
    const dept = depts.find((d) => d.id === id)
    setForm((f) => ({
      ...f,
      dept_id: id,
      major_field: dept?.major_field || f.major_field,
    }))
  }

  function addInterest() {
    const t = interestInput.trim()
    if (!t) return
    setForm((f) => (f.interests.includes(t) ? f : { ...f, interests: [...f.interests, t] }))
    setInterestInput('')
  }

  function removeInterest(t) {
    setForm((f) => ({ ...f, interests: f.interests.filter((x) => x !== t) }))
  }

  const dirty = useMemo(() => {
    if (!me || !form) return false
    return (
      (form.dept_id || null) !== (me.dept_id || null) ||
      (form.grade_year || null) !== (me.grade_year || null) ||
      (form.major_field || '') !== (me.major_field || '') ||
      JSON.stringify(form.interests) !== JSON.stringify(me.interests || [])
    )
  }, [me, form])

  async function save() {
    setSaving(true); setError(null); setMsg(null)
    try {
      const payload = {
        dept_id: form.dept_id === '' ? null : Number(form.dept_id),
        grade_year: form.grade_year === '' ? null : Number(form.grade_year),
        major_field: form.major_field || null,
        interests: form.interests,
      }
      // null은 '바꾸지 않음'이라 서버가 무시한다 → 빈 값은 아예 빼서 보낸다
      Object.keys(payload).forEach((k) => payload[k] === null && delete payload[k])
      const updated = await updateMe(payload)
      setMe(updated)
      // 헤더에 쓰는 사용자 정보도 최신으로 (학과가 바뀌면 다른 화면에 반영)
      if (user) saveUser({ ...user, dept_name: updated.dept_name })
      setMsg('저장했습니다.')
      setTimeout(() => setMsg(null), 3000)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function submitPassword() {
    setPwError(null); setPwMsg(null)
    if (!pw.current || !pw.next) { setPwError('현재 비밀번호와 새 비밀번호를 입력하세요.'); return }
    if (pw.next.length < 4) { setPwError('새 비밀번호는 4자 이상이어야 합니다.'); return }
    if (pw.next !== pw.confirm) { setPwError('새 비밀번호가 서로 다릅니다.'); return }
    setPwSaving(true)
    try {
      await changePassword(pw.current, pw.next)
      setPw({ current: '', next: '', confirm: '' })
      setPwMsg('비밀번호를 변경했습니다.')
      setTimeout(() => setPwMsg(null), 4000)
    } catch (e) {
      setPwError(e.message)
    } finally {
      setPwSaving(false)
    }
  }

  const inputCls = 'w-full border border-(--border) rounded-xl text-(--text) bg-(--surface-card) outline-none focus:border-(--brand) transition'
  const inputStyle = { padding: '11px 13px', fontSize: isMobile ? '16px' : '14px' }
  const labelCls = 'text-xs font-bold text-(--text-muted)'
  const cardCls = 'bg-(--surface-card) rounded-2xl shadow-sm border border-(--border)'
  const cardStyle = { padding: isMobile ? '18px 16px' : '24px 26px' }

  return (
    <main className="bg-(--page)" style={{ minHeight: '100dvh' }}>
      {/* 헤더 */}
      <header className="bg-(--brand) flex items-center shadow-sm"
              style={{ gap: '12px', padding: isMobile ? '12px' : '14px 24px' }}>
        <button onClick={() => navigate('/chat')}
                className="text-white/90 hover:text-white shrink-0" aria-label="채팅으로 돌아가기">
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <MascotAvatar className={isMobile ? 'h-8 w-8' : 'h-10 w-10'} />
        <h1 className="font-black text-white" style={{ fontSize: isMobile ? '16px' : '18px' }}>마이페이지</h1>
      </header>

      <div style={{ maxWidth: '760px', margin: '0 auto', padding: isMobile ? '16px 12px 40px' : '28px 20px 60px' }}>
        {loading && <p className="text-center text-(--text-faint) text-sm" style={{ padding: '60px' }}>불러오는 중…</p>}

        {!loading && me && (
          <>
            {/* 기본 정보 (수정 불가) */}
            <section className={cardCls} style={{ ...cardStyle, marginBottom: '16px' }}>
              <h2 className="font-black text-(--text)" style={{ fontSize: '15px', marginBottom: '14px' }}>기본 정보</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2" style={{ gap: '12px' }}>
                <div>
                  <p className={labelCls}>이름</p>
                  <p className="text-(--text)" style={{ fontSize: '15px', marginTop: '4px' }}>{me.name}</p>
                </div>
                <div>
                  <p className={labelCls}>학번</p>
                  <p className="text-(--text)" style={{ fontSize: '15px', marginTop: '4px' }}>{me.student_no}</p>
                </div>
              </div>
              <p className="text-[11px] text-(--text-faint)" style={{ marginTop: '12px' }}>
                이름과 학번은 변경할 수 없습니다. 잘못된 정보는 학사지원팀에 문의하세요.
              </p>
            </section>

            {/* 학적 정보 (수정 가능) */}
            <section className={cardCls} style={{ ...cardStyle, marginBottom: '16px' }}>
              <h2 className="font-black text-(--text)" style={{ fontSize: '15px' }}>학적 정보</h2>
              <p className="text-[11px] text-(--text-faint)" style={{ marginTop: '4px', marginBottom: '16px', lineHeight: 1.6 }}>
                맞춤 장학금 추천에 사용됩니다. 실제와 다르면 추천 결과가 맞지 않으니 확인해 주세요.
              </p>

              <div className="grid grid-cols-1 sm:grid-cols-2" style={{ gap: '14px' }}>
                <label className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>학과</span>
                  <select className={inputCls} style={inputStyle}
                          value={form.dept_id} onChange={(e) => onDeptChange(e.target.value)}>
                    <option value="">선택 안 함</option>
                    {depts.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.college ? `[${d.college}] ` : ''}{d.name}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>
                    전공계열 <span className="font-normal text-(--text-faint)">(학과 선택 시 자동)</span>
                  </span>
                  <select className={inputCls} style={inputStyle}
                          value={form.major_field}
                          onChange={(e) => setForm({ ...form, major_field: e.target.value })}>
                    <option value="">선택 안 함</option>
                    {MAJOR_FIELDS.map((f) => <option key={f} value={f}>{f}</option>)}
                  </select>
                </label>

                <label className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>학년</span>
                  <select className={inputCls} style={inputStyle}
                          value={form.grade_year}
                          onChange={(e) => setForm({ ...form, grade_year: e.target.value })}>
                    <option value="">선택 안 함</option>
                    {GRADES.map((g) => <option key={g} value={g}>{g}학년</option>)}
                  </select>
                </label>

                {/* 평점평균은 직접 입력받지 않는다 — 수강 이력에서 학점 가중 평균으로 계산되므로
                    손으로 고치면 과목 목록과 어긋난다. 아래 '수강 이력'에서 엑셀을 올리면 채워진다. */}
                <div className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>평점평균 <span className="font-normal text-(--text-faint)">(수강 이력에서 자동 계산)</span></span>
                  <div className="border border-(--border) rounded-xl bg-(--surface-2) flex items-center"
                       style={{ ...inputStyle, minHeight: '44px' }}>
                    {me.gpa != null
                      ? <span className="font-bold text-(--text)">{me.gpa} <span className="font-normal text-(--text-faint)">/ 4.5</span></span>
                      : <span className="text-(--text-faint)" style={{ fontSize: '13px' }}>아직 없음 — 아래에서 성적 엑셀을 올려주세요</span>}
                  </div>
                </div>
              </div>

              {/* 관심 목록 */}
              <div style={{ marginTop: '18px' }}>
                <span className={labelCls}>관심 목록</span>
                <p className="text-[11px] text-(--text-faint)" style={{ marginTop: '3px' }}>
                  관심 있는 주제를 등록해 두면 추천에 참고됩니다.
                </p>
                <div className="flex flex-wrap" style={{ gap: '6px', marginTop: '10px' }}>
                  {form.interests.map((t) => (
                    <span key={t}
                          className="inline-flex items-center rounded-full bg-(--brand-a10) text-(--brand) font-bold"
                          style={{ gap: '6px', padding: '5px 8px 5px 12px', fontSize: '12.5px' }}>
                      {t}
                      <button onClick={() => removeInterest(t)}
                              className="text-(--brand) hover:text-red-500 transition"
                              aria-label={`${t} 삭제`} style={{ fontSize: '14px', lineHeight: 1 }}>✕</button>
                    </span>
                  ))}
                  {form.interests.length === 0 && (
                    <span className="text-xs text-(--text-faint)">등록된 관심사가 없습니다.</span>
                  )}
                </div>
                <div className="flex" style={{ gap: '8px', marginTop: '10px' }}>
                  <input value={interestInput}
                         onChange={(e) => setInterestInput(e.target.value)}
                         onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addInterest() } }}
                         placeholder="예: 교환학생, 공모전"
                         className={inputCls} style={{ ...inputStyle, flex: 1 }} />
                  <button onClick={addInterest}
                          className="border border-(--brand-a20) rounded-xl text-sm font-bold text-(--brand) hover:bg-(--brand-a5) transition shrink-0"
                          style={{ padding: '0 18px' }}>추가</button>
                </div>
              </div>

              {error && <p className="text-xs font-bold text-red-500" style={{ marginTop: '14px' }}>{error}</p>}
              {msg && <p className="text-xs font-bold text-(--brand)" style={{ marginTop: '14px' }}>{msg}</p>}

              <button onClick={save} disabled={saving || !dirty}
                      className="w-full bg-(--brand) text-white rounded-xl font-black hover:bg-(--brand-hover) transition disabled:opacity-40 disabled:cursor-not-allowed"
                      style={{ padding: '13px', fontSize: '15px', marginTop: '18px' }}>
                {saving ? '저장 중…' : dirty ? '변경사항 저장' : '변경된 내용 없음'}
              </button>
            </section>

            {/* 수강 이력 — 평점평균·졸업 현황의 근거 데이터 */}
            <CourseSection onGpaChange={(gpa) => setMe((m) => ({ ...m, gpa }))} />

            {/* 비밀번호 변경 */}
            <section className={cardCls} style={cardStyle}>
              <h2 className="font-black text-(--text)" style={{ fontSize: '15px', marginBottom: '14px' }}>비밀번호 변경</h2>
              <div className="flex flex-col" style={{ gap: '12px' }}>
                <label className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>현재 비밀번호</span>
                  <input type="password" autoComplete="current-password"
                         className={inputCls} style={inputStyle}
                         value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
                </label>
                <label className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>새 비밀번호 <span className="font-normal text-(--text-faint)">(4자 이상)</span></span>
                  <input type="password" autoComplete="new-password"
                         className={inputCls} style={inputStyle}
                         value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
                </label>
                <label className="flex flex-col" style={{ gap: '5px' }}>
                  <span className={labelCls}>새 비밀번호 확인</span>
                  <input type="password" autoComplete="new-password"
                         className={inputCls} style={inputStyle}
                         value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} />
                </label>
              </div>

              {pwError && <p className="text-xs font-bold text-red-500" style={{ marginTop: '12px' }}>{pwError}</p>}
              {pwMsg && <p className="text-xs font-bold text-(--brand)" style={{ marginTop: '12px' }}>{pwMsg}</p>}

              <button onClick={submitPassword} disabled={pwSaving}
                      className="w-full border border-(--border) rounded-xl font-bold text-(--text-body) hover:bg-(--surface-2) transition disabled:opacity-50"
                      style={{ padding: '12px', fontSize: '14px', marginTop: '16px' }}>
                {pwSaving ? '변경 중…' : '비밀번호 변경'}
              </button>
              <p className="text-[11px] text-(--text-faint)" style={{ marginTop: '10px', lineHeight: 1.6 }}>
                변경해도 지금 로그인은 유지됩니다. 다른 기기에서 로그아웃하려면 해당 기기에서 직접 로그아웃하세요.
              </p>
            </section>
          </>
        )}

        {!loading && !me && error && (
          <div className={cardCls} style={{ ...cardStyle, textAlign: 'center' }}>
            <p className="text-sm text-red-500">{error}</p>
            <button onClick={load}
                    className="border border-(--border) rounded-xl text-sm font-bold text-(--text-muted) hover:bg-(--surface-2) transition"
                    style={{ padding: '10px 20px', marginTop: '14px' }}>다시 시도</button>
          </div>
        )}
      </div>
    </main>
  )
}
