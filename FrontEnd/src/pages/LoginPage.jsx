import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '../api/auth'
import { useAuth } from '../store/AuthContext'
import MascotAvatar from '../components/common/MascotAvatar'

export default function LoginPage() {
  const [studentNo, setStudentNo] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { saveUser } = useAuth()
  const navigate = useNavigate()

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
    <main className="flex min-h-screen items-center justify-center bg-[#e8eaed]">
      <div className="flex items-center justify-center w-full max-w-[500px] min-h-[900px] bg-[#ffffff] p-12 shadow-2xl  rounded-3xl">
      <section className="w-full max-w-[400px] bg-white px-10 py-12">

        {/* 마스코트 */}
        <div className="flex justify-center pt-4">
          <MascotAvatar className="h-44 w-44 object-contain" />
        </div>

        {/* 타이틀 */}
        <div className="mt-14 text-center">
          <h1 className="break-keep text-[1.6rem] font-black leading-snug text-[#05263d]">
            우송대학교 학사 지원<br />AI 어시스턴트 시스템
          </h1>
          <div className="h-5" />
          <p className="text-sm font-medium leading-6 text-slate-400">
            RAG 기반 LLM 엔진·정보 검색 및 맞춤형 학사 지원 서비스
          </p>
        </div>

        <div className="h-5" />

        {/* 폼 */}
        <form onSubmit={handleSubmit} className="flex flex-col gap-5">

          {/* 아이디 */}
          <label className="flex h-14 items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 focus-within:border-[#006b67] focus-within:ring-2 focus-within:ring-[#006b67]/15 transition">
            <svg className="h-5 w-5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 7.5a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.5 20.25a7.5 7.5 0 0 1 15 0" />
            </svg>
            <input
              type="text"
              placeholder="아이디를 입력하세요"
              value={studentNo}
              onChange={(e) => setStudentNo(e.target.value)}
              className="flex-1 bg-transparent text-base font-medium text-slate-900 outline-none placeholder:text-slate-400"
              autoComplete="username"
            />
          </label>

          {/* 비밀번호 */}
          <label className="flex h-14 items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 focus-within:border-[#006b67] focus-within:ring-2 focus-within:ring-[#006b67]/15 transition">
            <svg className="h-5 w-5 shrink-0 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z" />
            </svg>
            <input
              type={showPassword ? 'text' : 'password'}
              placeholder="비밀번호를 입력하세요"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="flex-1 bg-transparent text-base font-medium text-slate-900 outline-none placeholder:text-slate-400"
              autoComplete="current-password"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="shrink-0 text-slate-400 hover:text-slate-600 transition"
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
            <p className="rounded-xl bg-rose-50 px-4 py-3 text-sm font-medium text-rose-600">
              {error}
            </p>
          )}

          {/* 로그인 버튼 */}
          <button
            type="submit"
            disabled={loading}
            className="flex h-14 w-full items-center justify-center rounded-xl bg-[#006b67] text-base font-black text-white shadow-sm transition hover:bg-[#005b57] disabled:cursor-not-allowed disabled:opacity-60"
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

        <div className="h-5" />

        {/* 구분선 */}
        <div className="flex items-center gap-4">
          <div className="h-px flex-1 bg-slate-200" />
          <span className="text-sm font-medium text-slate-400">또는</span>
          <div className="h-px flex-1 bg-slate-200" />
        </div>

        <div className="h-5" />

        {/* SSO 버튼 */}
        <button
          type="button"
          className="flex h-14 w-full items-center justify-center gap-2.5 rounded-xl border border-slate-200 bg-white text-base font-black text-[#05263d] transition hover:bg-slate-50"
        >
          <svg className="h-5 w-5 shrink-0 text-[#006b67]" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 2.25 5 5.1v5.92c0 4.45 2.85 8.45 7 9.88 4.15-1.43 7-5.43 7-9.88V5.1l-7-2.85Zm2.9 7.85-3.45 4.35a1 1 0 0 1-1.52.05l-1.8-1.9 1.45-1.38 1 1.05 2.75-3.47 1.57 1.3Z" />
          </svg>
          통합인증(SSO) 로그인
        </button>

        <div className="h-5" />

        {/* 하단 링크 */}
        <div className="flex items-center justify-center gap-5 text-sm font-medium text-slate-400">
          <button type="button" className="hover:text-slate-600 transition">아이디 찾기</button>
          <span className="text-slate-300">|</span>
          <button type="button" className="hover:text-slate-600 transition">비밀번호 찾기</button>
        </div>

      </section>
      </div>
    </main>
  )
}
