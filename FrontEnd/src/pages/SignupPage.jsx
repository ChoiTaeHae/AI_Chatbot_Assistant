import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { signup, getSignupDepartments } from '../api/auth'
import { useAuth } from '../store/AuthContext'
import MascotAvatar from '../components/common/MascotAvatar'
import useIsMobile from '../hooks/useIsMobile'

const FIELD = 'flex items-center gap-3 rounded-xl border border-(--border) bg-(--surface-card) focus-within:border-(--brand) focus-within:ring-2 focus-within:ring-(--brand-a15) transition'
const FIELD_STYLE = { height: 'clamp(46px, 6.4vh, 56px)', padding: '0 16px' }
const INPUT = 'flex-1 bg-transparent text-base font-medium text-(--text) outline-none placeholder:text-(--text-faint)'

export default function SignupPage() {
  const [studentNo, setStudentNo] = useState('')
  const [name, setName] = useState('')
  const [deptId, setDeptId] = useState('')
  const [password, setPassword] = useState('')
  const [password2, setPassword2] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [depts, setDepts] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { saveUser } = useAuth()
  const navigate = useNavigate()
  const isShort = useIsMobile('(max-height: 620px)')

  useEffect(() => {
    getSignupDepartments()
      .then(setDepts)
      .catch(() => setDepts([]))   // 목록을 못 받아도 화면은 뜬다 — 그때는 안내만 보여 준다
  }, [])

  async function handleSubmit(e) {
    e.preventDefault()

    // 서버도 같은 규칙으로 다시 검사한다. 여기 검사는 왕복을 아끼려는 것일 뿐,
    // 이걸 통과했다고 서버가 믿지는 않는다(클라이언트 검증은 우회할 수 있으므로).
    if (!studentNo || !name || !deptId || !password) {
      setError('모든 항목을 입력해 주세요.')
      return
    }
    if (!/^\d{4,20}$/.test(studentNo)) {
      setError('학번은 숫자만 입력해 주세요.')
      return
    }
    if (password.length < 8) {
      setError('비밀번호는 8자 이상이어야 합니다.')
      return
    }
    if (password !== password2) {
      setError('비밀번호가 서로 다릅니다.')
      return
    }

    setError('')
    setLoading(true)
    try {
      const user = await signup({
        student_no: studentNo, password, name, dept_id: Number(deptId),
      })
      saveUser(user)      // 가입 즉시 로그인 상태 (서버가 토큰을 함께 준다)
      navigate('/chat')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main
      className="flex items-center justify-center bg-(--page)"
      style={{ minHeight: '100dvh', maxHeight: '100dvh', overflowY: 'auto', padding: 'clamp(12px, 3vh, 32px) 16px' }}
    >
      <section
        className="w-full bg-(--surface-card) shadow-2xl rounded-3xl flex flex-col"
        style={{
          maxWidth: '440px',
          padding: 'clamp(22px, 4vh, 44px) clamp(20px, 6vw, 40px)',
          gap: 'clamp(12px, 2.2vh, 22px)',
        }}
      >
        {!isShort && (
          <div className="flex justify-center">
            <MascotAvatar className="object-contain" style={{ height: 'clamp(64px, 12vh, 120px)', width: 'auto' }} />
          </div>
        )}

        <div className="text-center">
          <h1 className="break-keep font-black leading-snug text-(--text)" style={{ fontSize: 'clamp(1.15rem, 3.2vh, 1.5rem)' }}>
            회원가입
          </h1>
          <p className="font-medium text-(--text-faint)" style={{ fontSize: 'clamp(11.5px, 1.7vh, 14px)', lineHeight: 1.5, marginTop: 'clamp(6px, 1.2vh, 12px)' }}>
            학번으로 가입하면 내 학과·학번 기준으로 답변해 드려요
          </p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col" style={{ gap: 'clamp(10px, 1.6vh, 16px)' }}>

          {/* 학번 */}
          <label className={FIELD} style={FIELD_STYLE}>
            <svg className="h-5 w-5 shrink-0 text-(--text-faint)" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4.26 10.147a60.438 60.438 0 0 0-.491 6.347A48.62 48.62 0 0 1 12 20.904a48.62 48.62 0 0 1 8.232-4.41 60.46 60.46 0 0 0-.491-6.347m-15.482 0a50.636 50.636 0 0 0-2.658-.813A59.906 59.906 0 0 1 12 3.493a59.903 59.903 0 0 1 10.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.717 50.717 0 0 1 12 13.489a50.702 50.702 0 0 1 7.74-3.342" />
            </svg>
            <input
              type="text" inputMode="numeric" placeholder="학번 (숫자만)"
              value={studentNo} onChange={(e) => setStudentNo(e.target.value)}
              className={INPUT} autoComplete="username" maxLength={20}
            />
          </label>

          {/* 이름 */}
          <label className={FIELD} style={FIELD_STYLE}>
            <svg className="h-5 w-5 shrink-0 text-(--text-faint)" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 7.5a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.5 20.25a7.5 7.5 0 0 1 15 0" />
            </svg>
            <input
              type="text" placeholder="이름"
              value={name} onChange={(e) => setName(e.target.value)}
              className={INPUT} autoComplete="name" maxLength={20}
            />
          </label>

          {/* 학과 */}
          <label className={FIELD} style={FIELD_STYLE}>
            <svg className="h-5 w-5 shrink-0 text-(--text-faint)" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 21h16.5M4.5 3h15M5.25 3v18m13.5-18v18M9 6.75h1.5m-1.5 3h1.5m-1.5 3h1.5m3-6H15m-1.5 3H15m-1.5 3H15M9 21v-3.375c0-.621.504-1.125 1.125-1.125h3.75c.621 0 1.125.504 1.125 1.125V21" />
            </svg>
            <select
              value={deptId}
              onChange={(e) => setDeptId(e.target.value)}
              className={`${INPUT} cursor-pointer`}
              style={{ appearance: 'none' }}
            >
              <option value="" className="text-(--text-faint) bg-(--surface-card)">
                {depts.length ? '학과를 선택하세요' : '학과 목록을 불러오는 중…'}
              </option>
              {depts.map((d) => (
                <option key={d.id} value={d.id} className="text-(--text) bg-(--surface-card)">{d.name}</option>
              ))}
            </select>
            <svg className="h-4 w-4 shrink-0 text-(--text-faint)" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </label>

          {/* 비밀번호 */}
          <label className={FIELD} style={FIELD_STYLE}>
            <svg className="h-5 w-5 shrink-0 text-(--text-faint)" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
            </svg>
            <input
              type={showPassword ? 'text' : 'password'} placeholder="비밀번호 (8자 이상)"
              value={password} onChange={(e) => setPassword(e.target.value)}
              className={INPUT} autoComplete="new-password" maxLength={128}
            />
            <button
              type="button" onClick={() => setShowPassword((v) => !v)} tabIndex={-1}
              className="shrink-0 text-(--text-faint) hover:text-(--text-muted) transition"
            >
              {showPassword ? (
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 0 1-4.293 5.774M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88" />
                </svg>
              ) : (
                <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                </svg>
              )}
            </button>
          </label>

          {/* 비밀번호 확인 */}
          <label className={FIELD} style={FIELD_STYLE}>
            <svg className="h-5 w-5 shrink-0 text-(--text-faint)" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
            </svg>
            <input
              type={showPassword ? 'text' : 'password'} placeholder="비밀번호 확인"
              value={password2} onChange={(e) => setPassword2(e.target.value)}
              className={INPUT} autoComplete="new-password" maxLength={128}
            />
          </label>

          {error && (
            <p className="rounded-xl bg-rose-50 text-sm font-medium text-rose-600" style={{ padding: '12px 16px' }}>
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="flex w-full items-center justify-center rounded-xl bg-(--brand) text-base font-black text-white shadow-sm transition hover:bg-(--brand-hover) disabled:cursor-not-allowed disabled:opacity-60"
            style={{ height: 'clamp(46px, 6.4vh, 56px)', marginTop: '4px' }}
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                가입 중...
              </span>
            ) : '가입하고 시작하기'}
          </button>
        </form>

        <div className="flex items-center justify-center gap-2 text-sm font-medium text-(--text-faint)">
          이미 계정이 있으신가요?
          <Link to="/login" className="font-bold text-(--brand) hover:underline">로그인</Link>
        </div>
      </section>
    </main>
  )
}
