import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import ChatWindow from '../components/chat/ChatWindow'
import ChatInput from '../components/chat/ChatInput'
import MascotAvatar from '../components/common/MascotAvatar'
import { logout } from '../api/auth'
import { useAuth } from '../store/AuthContext'
import { useChat } from '../hooks/useChat'

export default function ChatPage() {
  const { messages, isLoading, send, reset } = useChat()
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const profileRef = useRef(null)
  const { user, clearUser } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    clearUser()
    navigate('/login')
  }

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
    <main className="flex min-h-screen bg-[#e8eaed] items-center justify-center py-8 px-6">
      <div className="flex flex-col w-full max-w-[700px] h-[calc(100vh-64px)] bg-white rounded-2xl shadow-2xl overflow-hidden ">

        {/* 헤더 */}
        <header className="shrink-0 bg-[#005956] flex items-center justify-between shadow-sm z-10" style={{ padding: '10px 25px' }}>
          <div className="flex items-center gap-3">
            <MascotAvatar className="h-13 w-13 object-contain" />
            <span className="text-white font-bold text-lg">AI 어시스턴트</span>
          </div>

          <div className="flex items-center gap-4">
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
                <div className="absolute right-0 top-full mt-2 w-52 bg-white rounded-2xl shadow-lg border border-slate-100 overflow-hidden z-50">

                  {/* 관리자 페이지 (admin만) */}
                  {user?.role === 'admin' && (
                    <button
                      onClick={() => { setDropdownOpen(false); navigate('/admin') }}
                      className="w-full flex items-center text-sm text-slate-600 hover:bg-[#005956]/5 hover:text-[#005956] transition"
                      style={{ gap: '10px', padding: '12px 16px' }}
                    >
                      <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 17.25v1.007a3 3 0 01-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0115 18.257V17.25m6-12V15a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 15V5.25m18 0A2.25 2.25 0 0018.75 3H5.25A2.25 2.25 0 003 5.25m18 0H3" />
                      </svg>
                      관리자 페이지
                    </button>
                  )}

                  {/* 로그아웃 */}
                  <button
                    onClick={() => { setDropdownOpen(false); handleLogout() }}
                    className="w-full flex items-center text-sm text-red-500 hover:bg-red-50 transition border-t border-slate-50"
                    style={{ gap: '10px', padding: '12px 16px' }}
                  >
                    <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
                    </svg>
                    로그아웃
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        <div className="flex-1 flex flex-col min-h-0">
          <ChatWindow messages={messages} isLoading={isLoading} />
          <ChatInput onSend={send} disabled={isLoading} />
        </div>      
      </div>
    </main>
  )
}