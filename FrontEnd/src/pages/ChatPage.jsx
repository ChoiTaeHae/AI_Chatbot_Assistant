import { useState } from 'react'
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
  const { user, clearUser } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    clearUser()
    navigate('/login')
  }

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
            <button className="relative text-white hover:text-slate-200 transition">
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
              </svg>
              <span className="absolute top-0 right-0 h-2 w-2 rounded-full bg-red-500" />
            </button>

            <div className="relative">
              <button
                onClick={() => setDropdownOpen((v) => !v)}
                className="flex items-center gap-2 text-white hover:bg-white/10 rounded-lg px-2 py-1 transition"
              >
                <div className="h-8 w-8 rounded-full bg-white text-[#005956] flex items-center justify-center font-bold text-sm">
                  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                  </svg>
                </div>
                <span className="font-medium text-sm">{user?.name || '홍길동'}</span>
                <svg className={`h-4 w-4 transition-transform ${dropdownOpen ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {dropdownOpen && (
                <div className="absolute right-0 top-full mt-2 w-40 bg-white rounded-lg shadow-lg border border-slate-100 overflow-hidden z-50">
                  {user?.role === 'admin' && (
                    <button
                      onClick={() => { setDropdownOpen(false); navigate('/admin') }}
                      className="w-full flex items-center gap-2 px-4 py-3 text-sm font-medium text-[#005956] hover:bg-[#005956]/5 transition border-b border-slate-100"
                    >
                      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 17.25v1.007a3 3 0 01-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0115 18.257V17.25m6-12V15a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 15V5.25m18 0A2.25 2.25 0 0018.75 3H5.25A2.25 2.25 0 003 5.25m18 0H3" />
                      </svg>
                      관리자 페이지
                    </button>
                  )}
                  <button
                    onClick={handleLogout}
                    className="w-full flex items-center gap-2 px-4 py-3 text-sm font-medium text-red-500 hover:bg-red-50 transition"
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
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