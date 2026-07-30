import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import ChatWindow from '../components/chat/ChatWindow'
import ChatInput from '../components/chat/ChatInput'
import Sidebar from '../components/chat/Sidebar'
import ScholarshipModal from '../components/chat/ScholarshipModal'
import ScholarshipSurveyModal from '../components/chat/ScholarshipSurveyModal'
import MascotAvatar from '../components/common/MascotAvatar'
import ThemeToggle from '../components/common/ThemeToggle'
import { logout } from '../api/auth'
import { useAuth } from '../store/AuthContext'
import { useChat } from '../hooks/useChat'

const LANGUAGES = [
  { code: 'ko', label: '한국어' },
  { code: 'en', label: 'English' },
  { code: 'zh', label: '中文' },
]

const T = {
  ko: { title: 'AI 어시스턴트', admin: '관리자 페이지', logout: '로그아웃', grad: '🎓 내 졸업 현황' },
  en: { title: 'AI Assistant',   admin: 'Admin Page',    logout: 'Logout',   grad: '🎓 My Graduation Status' },
  zh: { title: 'AI助手',          admin: '管理员页面',      logout: '退出登录',  grad: '🎓 我的毕业进度' },
}

export default function ChatPage() {
  const [lang, setLang] = useState('ko')
  const { messages, isLoading, send, confirmFile, checkGraduation, reset, loadSession, sessionId, clearPendingFile, pendingFile, viewKey } = useChat(lang)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  // 장학금 둘러보기 모달(사이드바 버튼·설문 결과 딥링크가 공유) · 맞춤 설문 모달
  const [scholarship, setScholarship] = useState(null)   // null=닫힘. { scope, categories?, query? }
  const [survey, setSurvey] = useState(false)
  const openScholarship = (opts = null) => setScholarship(opts || { scope: '교내' })
  const [sessionsRefresh, setSessionsRefresh] = useState(0)
  const profileRef = useRef(null)
  const { user, clearUser } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    clearUser()
    navigate('/login')
  }

  // 새 세션이 생성(첫 메시지)되거나 다른 세션으로 전환되면 사이드바 '최근 대화' 목록 갱신
  useEffect(() => {
    if (sessionId) setSessionsRefresh((v) => v + 1)
  }, [sessionId])

  // 드롭다운 바깥 클릭 시 닫기
  useEffect(() => {
    function handleClickOutside(e) {
      if (profileRef.current && !profileRef.current.contains(e.target)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return ( 
    // 배경을 흰색으로, 중앙 정렬 컨테이너를 조금 더 넓게 설정
    <main className="flex min-h-[100dvh] bg-(--page) items-center justify-center py-4 px-2 sm:py-8 sm:px-6">
      <div className="flex w-full max-w-6xl h-[calc(100dvh-2rem)] sm:h-[calc(100vh-4rem)]">

        {/* 사이드바 (슬라이드로 접기/펴기) */}
        {/* 여백은 전역 `* { margin: 0 }` 리셋이 Tailwind mr-* 유틸을 덮어써서 인라인 style로 처리 */}
        <div
          className={`hidden md:block shrink-0 overflow-hidden transition-all duration-300 ${sidebarOpen ? 'w-[264px]' : 'w-0'}`}
          style={{ marginRight: sidebarOpen ? '24px' : '0' }}
        >
          <Sidebar lang={lang} role={user?.role} onNewChat={reset} onSelectSession={loadSession} activeSessionId={sessionId} onSessionDeleted={reset} refreshTrigger={sessionsRefresh} onOpenScholarship={openScholarship} />
        </div>

        {/* 채팅 카드 */}
        <div className="flex flex-col flex-1 min-w-0 bg-(--surface-card) rounded-2xl shadow-2xl overflow-hidden">

        {/* 헤더 */}
        <header className="shrink-0 bg-(--brand) flex items-center justify-between shadow-sm z-10" style={{ padding: '10px 25px' }}>
          <div className="flex items-center gap-3">
            {/* 사이드바 접기/펴기 (데스크톱) */}
            <button
              onClick={() => setSidebarOpen((v) => !v)}
              className="hidden md:inline-flex items-center justify-center h-9 w-9 rounded-lg text-white hover:bg-white/10 transition"
              aria-label="사이드바 토글"
            >
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <MascotAvatar className="h-13 w-13 object-contain" />
            <span className="text-white font-bold text-lg">{T[lang].title}</span>
          </div>

          <div className="flex items-center gap-3">

            {/* 다크모드 토글 */}
            <ThemeToggle className="inline-flex items-center justify-center h-9 w-9 rounded-lg text-white hover:bg-white/10 transition" />

            {/* 언어 선택 드롭다운 */}
            <select
              value={lang}
              onChange={(e) => setLang(e.target.value)}
              className="text-xs font-semibold bg-white/10 text-white border border-white/20 rounded-lg outline-none cursor-pointer hover:bg-white/20 transition"
              style={{ padding: '5px 8px' }}
            >
              {LANGUAGES.map(({ code, label }) => (
                <option key={code} value={code} className="text-(--text) bg-(--surface-card)">
                  {label}
                </option>
              ))}
            </select>

            {/* 프로필 드롭다운 */}
            <div className="relative" ref={profileRef}>
              <button
                onClick={() => setDropdownOpen(v => !v)}
                className="flex items-center gap-2 text-white hover:bg-white/10 rounded-xl px-2 py-1.5 transition"
              >
                <div className="h-8 w-8 rounded-full bg-white/20 text-white flex items-center justify-center">
                  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                </div>
                <div className="text-left">
                  <p className="text-sm font-bold leading-tight">{user?.name || '홍길동'}</p>
                  <p className="text-xs text-white/60 leading-tight">{user?.role === 'admin' ? 'Admin' : 'Student'}</p>
                </div>
                <svg className={`h-4 w-4 text-white/70 transition-transform ${dropdownOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {dropdownOpen && (
                <div className="absolute right-0 top-full mt-2 w-52 bg-(--surface-card) rounded-2xl shadow-lg border border-(--border) overflow-hidden z-50">

                  {/* 관리자 페이지 (admin만) */}
                  {user?.role === 'admin' && (
                    <button
                      onClick={() => { setDropdownOpen(false); navigate('/admin') }}
                      className="w-full flex items-center text-sm text-(--text-muted) hover:bg-(--brand-a5) hover:text-(--brand) transition"
                      style={{ gap: '10px', padding: '12px 16px' }}
                    >
                      <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 17.25v1.007a3 3 0 01-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0115 18.257V17.25m6-12V15a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 15V5.25m18 0A2.25 2.25 0 0018.75 3H5.25A2.25 2.25 0 003 5.25m18 0H3" />
                      </svg>
                      {T[lang].admin}
                    </button>
                  )}

                  {/* 로그아웃 */}
                  <button
                    onClick={() => { setDropdownOpen(false); handleLogout() }}
                    className="w-full flex items-center text-sm text-red-500 hover:bg-red-50 transition border-t border-(--border)"
                    style={{ gap: '10px', padding: '12px 16px' }}
                  >
                    <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
                    </svg>
                    {T[lang].logout}
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        <div className="flex-1 flex flex-col min-h-0">
          <ChatWindow
            key={viewKey}
            messages={messages}
            isLoading={isLoading}
            lang={lang}
            onClearPendingFile={clearPendingFile}
            pendingFile={pendingFile}
            onConfirmFile={confirmFile}
            onCheckGraduation={checkGraduation}
            onSendQuestion={send}
            onStartSurvey={() => setSurvey(true)}
          />
          <ChatInput onSend={send} disabled={isLoading} lang={lang} />
        </div>
        </div>
      </div>

      {/* 장학·근로 둘러보기 모달 — 사이드바 버튼/채팅 카드 어느 쪽에서 열어도 이 하나가 뜬다 */}
      {/* 맞춤 장학금 설문 — 결과에서 장학금을 고르면 둘러보기 모달을 그 장학금으로 연다(딥링크).
          설문 모달은 계속 떠 있고 그 위에 둘러보기 모달이 겹쳐, '뒤로'로 결과 목록에 돌아가 다시 고를 수 있다.
          (겹침 순서상 둘러보기 모달이 나중에 렌더돼 위에 온다) */}
      {survey && (
        <ScholarshipSurveyModal
          onClose={() => setSurvey(false)}
          onPick={(item) => setScholarship({ scope: '전체', query: item.name, fromSurvey: true })}
        />
      )}

      {scholarship && (
        <ScholarshipModal
          lang={lang}
          initialScope={scholarship.scope || '교내'}
          initialCategories={scholarship.categories || null}
          initialQuery={scholarship.query || ''}
          onBack={scholarship.fromSurvey ? () => setScholarship(null) : undefined}
          onClose={() => { setScholarship(null); setSurvey(false) }}
        />
      )}
    </main>
  )
}
