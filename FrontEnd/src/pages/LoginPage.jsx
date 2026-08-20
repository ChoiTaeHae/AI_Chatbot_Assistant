import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { login } from '../api/auth'
import { useAuth } from '../store/AuthContext'
import MascotAvatar from '../components/common/MascotAvatar'
import useIsMobile from '../hooks/useIsMobile'

export default function LoginPage() {
  const [studentNo, setStudentNo] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { saveUser, enterGuest } = useAuth()
  const navigate = useNavigate()
  // 세로가 아주 낮은 화면(폰 가로 등) — 마스코트를 접어 폼이 먼저 보이게 한다.
  // 그래도 다 안 들어가면 main의 overflowY:auto가 받아준다(잘리지 않음).
  const isShort = useIsMobile('(max-height: 500px)')

  async function handleSubmit(e) {
    e.preventDefault()  //새로고침 방지

    if (!studentNo || !password) {
      setError('아이디와 비밀번호를 입력해주세요.')
      return
    }
    setError('')
    setLoading(true) //로그인 중이라고 바꿈
    try {
      const user = await login(studentNo, password)  //밖에서 가죠온 login 함수를 통해 로그인 시도
      saveUser(user) //성공하면 user 정보 받아옴
      navigate('/chat') //chat 페이지로 이동
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    /* 화면 높이에 맞춰 들어가도록 — 예전엔 카드에 min-h-[900px]가 박혀 있어 뷰포트가
       900px보다 낮은 노트북·태블릿 가로에서 무조건 스크롤이 생겼다. 이제 세로 여백·글자·
       마스코트를 vh 기반 clamp로 줄여 한 화면에 담고, 그래도 모자라면(아주 낮은 창) 그때만
       스크롤한다. 여백을 인라인으로 준 이유는 전역 `* { padding: 0 }` 리셋이 Tailwind의
       p-* 유틸을 덮어써 클래스로는 여백이 먹지 않기 때문. */
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

        {/* 마스코트 — 세로가 좁을수록 작아지고, 아주 낮으면 아예 숨긴다 */}
        {!isShort && (
          <div className="flex justify-center">
            <MascotAvatar className="object-contain" style={{ height: 'clamp(72px, 15vh, 168px)', width: 'auto' }} />
          </div>
        )}

        {/* 타이틀 */}
        <div className="text-center">
          <h1 className="break-keep font-black leading-snug text-(--text)" style={{ fontSize: 'clamp(1.15rem, 3.2vh, 1.6rem)' }}>
            우송대학교 학사 지원<br />AI 캠퍼스 코치 시스템
          </h1>
          <p className="font-medium text-(--text-faint)" style={{ fontSize: 'clamp(11.5px, 1.7vh, 14px)', lineHeight: 1.5, marginTop: 'clamp(8px, 1.6vh, 16px)' }}>
            RAG 기반 LLM 엔진·정보 검색 및 맞춤형 학사 지원 서비스
          </p>
        </div>

        {/* 폼 */}
        <form onSubmit={handleSubmit} className="flex flex-col" style={{ gap: 'clamp(10px, 1.8vh, 20px)' }}>

          {/* 아이디 */}
          <label className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--surface-card) focus-within:border-(--brand) focus-within:ring-2 focus-within:ring-(--brand-a15) transition" style={{ height: 'clamp(46px, 6.4vh, 56px)', padding: '0 16px' }}>
            <svg className="h-5 w-5 shrink-0 text-(--text-faint)" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 7.5a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.5 20.25a7.5 7.5 0 0 1 15 0" />
            </svg>
            <input
              type="text"
              placeholder="아이디를 입력하세요"
              value={studentNo}
              onChange={(e) => setStudentNo(e.target.value)}
              className="flex-1 bg-transparent text-base font-medium text-(--text) outline-none placeholder:text-(--text-faint)"
              autoComplete="username"
            />
          </label>

          {/* 비밀번호 */}
          <label className="flex items-center gap-3 rounded-xl border border-(--border) bg-(--surface-card) focus-within:border-(--brand) focus-within:ring-2 focus-within:ring-(--brand-a15) transition" style={{ height: 'clamp(46px, 6.4vh, 56px)', padding: '0 16px' }}>
            <svg className="h-5 w-5 shrink-0 text-(--text-faint)" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
            </svg>
            <input
              type={showPassword ? 'text' : 'password'}
              placeholder="비밀번호를 입력하세요"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="flex-1 bg-transparent text-base font-medium text-(--text) outline-none placeholder:text-(--text-faint)"
              autoComplete="current-password"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="shrink-0 text-(--text-faint) hover:text-(--text-muted) transition"
              tabIndex={-1}
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

          {/* 에러 */}
          {error && (
            <p className="rounded-xl bg-rose-50 text-sm font-medium text-rose-600" style={{ padding: '12px 16px' }}>
              {error}
            </p>
          )}

          {/* 로그인 버튼 */}
          <button
            type="submit"
            disabled={loading}
            className="flex w-full items-center justify-center rounded-xl bg-(--brand) text-base font-black text-white shadow-sm transition hover:bg-(--brand-hover) disabled:cursor-not-allowed disabled:opacity-60"
            style={{ height: 'clamp(46px, 6.4vh, 56px)' }}
          >
            {loading ? (
              <span className="flex items-center gap-2">
                <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                로그인 중...
              </span>
            ) : '로그인'}
          </button>
        </form>

        {/* 구분선 */}
        <div className="flex items-center gap-4">
          <div className="h-px flex-1 bg-(--border)" />
          <span className="text-sm font-medium text-(--text-faint)">또는</span>
          <div className="h-px flex-1 bg-(--border)" />
        </div>

        {/* SSO 버튼 */}
        <button
          type="button"
          className="flex w-full items-center justify-center gap-2.5 rounded-xl border border-(--border) bg-(--surface-card) text-base font-black text-(--text) transition hover:bg-(--surface-2)"
          style={{ height: 'clamp(46px, 6.4vh, 56px)' }}
        >
          <svg className="h-5 w-5 shrink-0 text-(--brand)" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 2.25 5 5.1v5.92c0 4.45 2.85 8.45 7 9.88 4.15-1.43 7-5.43 7-9.88V5.1l-7-2.85Zm2.9 7.85-3.45 4.35a1 1 0 0 1-1.52.05l-1.8-1.9 1.45-1.38 1 1.05 2.75-3.47 1.57 1.3Z" />
          </svg>
          통합인증(SSO) 로그인
        </button>

        {/* 로그인 없이 둘러보기 — 학사 규정·일정·학식·위치·학과·서식은 로그인 없이도 쓸 수 있다.
            성적·졸업요건처럼 학번이 있어야 답할 수 있는 것만 그때 로그인을 안내한다. */}
        <button
          type="button"
          onClick={() => { enterGuest(); navigate('/chat') }}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-(--border) bg-transparent text-sm font-bold text-(--text-muted) transition hover:border-(--brand-a40) hover:text-(--brand) hover:bg-(--brand-a5)"
          style={{ height: 'clamp(42px, 5.6vh, 50px)' }}
        >
          로그인 없이 둘러보기
          <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5 21 12m0 0-7.5 7.5M21 12H3" />
          </svg>
        </button>

        {/* 하단 링크 */}
        <div className="flex items-center justify-center gap-5 text-sm font-medium text-(--text-faint)">
          <Link to="/signup" className="font-bold text-(--brand) hover:underline">회원가입</Link>
          <span className="text-(--text-faint)">|</span>
          <button type="button" className="hover:text-(--text-muted) transition">아이디 찾기</button>
          <span className="text-(--text-faint)">|</span>
          <button type="button" className="hover:text-(--text-muted) transition">비밀번호 찾기</button>
        </div>

      </section>
    </main>
  )
}
