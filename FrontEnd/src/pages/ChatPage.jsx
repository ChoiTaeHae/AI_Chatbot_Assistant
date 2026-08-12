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
import useIsMobile from '../hooks/useIsMobile'

const LANGUAGES = [
  { code: 'ko', label: '한국어' },
  { code: 'en', label: 'English' },
  { code: 'zh', label: '中文' },
]

const T = {
  ko: { title: 'AI 캠퍼스 코치', admin: '관리자 페이지', mypage: '마이페이지', logout: '로그아웃', grad: '🎓 내 졸업 현황', menu: '메뉴 열기' },
  en: { title: 'AI Assistant',   admin: 'Admin Page',    mypage: 'My Page',  logout: 'Logout',   grad: '🎓 My Graduation Status', menu: 'Open menu' },
  zh: { title: 'AI助手',          admin: '管理员页面',      mypage: '我的页面', logout: '退出登录',  grad: '🎓 我的毕业进度', menu: '打开菜单' },
}

export default function ChatPage() {
  const isMobile = useIsMobile()
  const [lang, setLang] = useState('ko')
  const { messages, isLoading, send, confirmFile, checkGraduation, reset, loadSession, sessionId, clearPendingFile, pendingFile, viewKey } = useChat(lang)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  // 모바일 드로어는 데스크톱 접기 상태와 별개로 둔다 — 한 상태로 묶으면 폰에서 열었다
  // 닫은 것이 데스크톱 화면 폭에서 사이드바가 접힌 상태로 남는다.
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  // 슬라이드 상태를 마운트와 분리한다. 한 값으로 하면 닫을 때 DOM이 즉시 사라져
  // 나가는 애니메이션이 보이지 않는다(열 때만 움직이고 닫을 땐 뚝 끊김).
  const [navIn, setNavIn] = useState(false)
  const openNav = () => { setMobileNavOpen(true); requestAnimationFrame(() => setNavIn(true)) }
  const closeNav = () => { setNavIn(false); setTimeout(() => setMobileNavOpen(false), 300) }
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
    /* 높이를 100dvh로 고정하고 바깥 여백은 인라인으로 준다.
       예전엔 h-[calc(100vh-4rem)]가 sm:py-8(4rem)을 전제했는데, 전역 `* { padding: 0 }`
       리셋이 그 패딩 유틸을 덮어써 실제 여백은 0이었다 → 아래쪽에 4rem이 그대로 비었다.
       이제 main이 padding을 갖고(box-sizing: border-box) 안쪽은 height:100%라, 여백 값을
       바꿔도 계산이 저절로 맞는다. 태블릿 가로/세로 전환도 dvh가 알아서 따라온다. */
    <main
      className="flex bg-(--page) items-center justify-center"
      style={{
        // position:fixed + inset:0 — 앱 셸을 뷰포트에 고정한다. height:100dvh만 쓰면
        // 모바일 브라우저가 주소창을 접었다 펴는 동안 문서가 뷰포트보다 커져 페이지가
        // 통째로 스크롤됐다(태블릿 세로에서 카드 아래로 빈 공간이 밀려 나오던 현상).
        // fixed는 문서 높이에 기여하지 않으므로 페이지 스크롤 자체가 생기지 않는다.
        position: 'fixed', inset: 0, overflow: 'hidden',
        padding: isMobile ? '0' : 'clamp(10px, 2.2vh, 32px) clamp(10px, 2vw, 24px)',
      }}
    >
      <div className="flex w-full max-w-6xl" style={{ height: '100%' }}>

        {/* 사이드바 — 데스크톱(md+)은 좌측에 붙어 접기/펴기 */}
        {/* 여백은 전역 `* { margin: 0 }` 리셋이 Tailwind mr-* 유틸을 덮어써서 인라인 style로 처리 */}
        <div
          className={`hidden md:block shrink-0 overflow-hidden transition-all duration-300 ${sidebarOpen ? 'w-[264px]' : 'w-0'}`}
          style={{ marginRight: sidebarOpen ? '24px' : '0' }}
        >
          <Sidebar lang={lang} role={user?.role} onNewChat={reset} onSelectSession={loadSession} activeSessionId={sessionId} onSessionDeleted={reset} refreshTrigger={sessionsRefresh} onOpenScholarship={openScholarship} />
        </div>

        {/* 사이드바 — 모바일(md 미만)은 화면 위로 덮는 드로어.
            예전엔 `hidden md:block` 하나뿐이라 모바일에서 통째로 사라져
            대화 목록·새 대화·장학금 둘러보기에 접근할 방법이 없었다. */}
        {mobileNavOpen && (
          <div className="md:hidden fixed inset-0 z-50 flex">
            <div
              className={`absolute inset-0 bg-black/50 transition-opacity duration-300 ${navIn ? 'opacity-100' : 'opacity-0'}`}
              onClick={closeNav}
              aria-hidden="true"
            />
            {/* 왼쪽 벽에 붙여 밀려나오는 패널. Sidebar 자체 폭·둥근 모서리는 여기서 덮어써
                오른쪽 모서리만 둥글게 남긴다(붙어 있는 왼쪽은 각지게). */}
            <div
              className={`relative h-full transition-transform duration-300 ease-out
                [&>aside]:w-full [&>aside]:h-full [&>aside]:rounded-none [&>aside]:rounded-r-2xl [&>aside]:border-l-0
                ${navIn ? 'translate-x-0' : '-translate-x-full'}`}
              style={{ width: '272px', maxWidth: '84vw' }}
            >
              <Sidebar
                lang={lang} role={user?.role}
                onNewChat={() => { closeNav(); reset() }}
                onSelectSession={(sid) => { closeNav(); loadSession(sid) }}
                activeSessionId={sessionId}
                onSessionDeleted={reset}
                refreshTrigger={sessionsRefresh}
                onOpenScholarship={(opts) => { closeNav(); openScholarship(opts) }}
              />
            </div>
          </div>
        )}

        {/* 채팅 카드 */}
        <div className="flex flex-col flex-1 min-w-0 bg-(--surface-card) rounded-none sm:rounded-2xl shadow-2xl overflow-hidden">

        {/* 헤더 */}
        <header className="shrink-0 bg-(--brand) flex items-center justify-between gap-2 shadow-sm z-10" style={{ padding: isMobile ? '12px' : '10px 24px' }}>
          <div className="flex items-center gap-2 sm:gap-3 min-w-0">
            {/* 사이드바 접기/펴기 (데스크톱) */}
            <button
              onClick={() => setSidebarOpen((v) => !v)}
              className="hidden md:inline-flex shrink-0 items-center justify-center h-9 w-9 rounded-lg text-white hover:bg-white/10 transition"
              aria-label="사이드바 토글"
            >
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            {/* 메뉴 열기 (모바일) — 같은 자리에 놓아 데스크톱과 위치가 일관되게 */}
            <button
              onClick={openNav}
              className="md:hidden inline-flex shrink-0 items-center justify-center h-9 w-9 rounded-lg text-white hover:bg-white/10 transition"
              aria-label={T[lang].menu}
              aria-expanded={mobileNavOpen}
            >
              <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <MascotAvatar className="h-10 w-10 sm:h-13 sm:w-13 shrink-0 object-contain" />
            <span className="text-white font-bold text-base sm:text-lg whitespace-nowrap truncate min-w-0">{T[lang].title}</span>
          </div>

          <div className="flex items-center gap-1.5 sm:gap-3 shrink-0">

            {/* 다크모드 토글 */}
            <ThemeToggle className="inline-flex items-center justify-center h-9 w-9 rounded-lg text-white hover:bg-white/10 transition" />

            {/* 언어 선택 드롭다운 */}
            <select
              value={lang}
              onChange={(e) => setLang(e.target.value)}
              className="text-[16px] sm:text-xs font-semibold bg-white/10 text-white border border-white/20 rounded-lg outline-none cursor-pointer hover:bg-white/20 transition"
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
                  <p className="hidden sm:block text-sm font-bold leading-tight">{user?.name || '홍길동'}</p>
                  <p className="text-xs text-white/60 leading-tight">{user?.role === 'admin' ? 'Admin' : 'Student'}</p>
                </div>
                <svg className={`h-4 w-4 text-white/70 transition-transform ${dropdownOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {dropdownOpen && (
                <div className="absolute right-0 top-full mt-2 w-52 bg-(--surface-card) rounded-2xl shadow-lg border border-(--border) overflow-hidden z-50">

                  {/* 마이페이지 */}
                  <button
                    onClick={() => { setDropdownOpen(false); navigate('/mypage') }}
                    className="w-full flex items-center text-sm text-(--text-muted) hover:bg-(--brand-a5) hover:text-(--brand) transition"
                    style={{ gap: '10px', padding: '12px 16px' }}
                  >
                    <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
                    </svg>
                    {T[lang].mypage}
                  </button>

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
          onOpenSurvey={() => { setScholarship(null); setSurvey(true) }}
          onClose={() => { setScholarship(null); setSurvey(false) }}
        />
      )}
    </main>
  )
}
