import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './store/AuthContext'
import LoginPage from './pages/LoginPage'
import SignupPage from './pages/SignupPage'
import ChatPage from './pages/ChatPage'
import AdminPage from './pages/AdminPage'
import MyPage from './pages/MyPage'

function ProtectedRoute({ children }) {
  const { user } = useAuth()
  return user ? children : <Navigate to="/login" replace />
}

// 채팅은 로그인 없이도 들어올 수 있다. 다만 '둘러보기'를 눌러 게스트로 전환한 사람만이다 —
// 아무나 /chat 주소를 치면 로그인 화면을 먼저 보여준다(입구를 하나로 유지).
// 개인 데이터가 필요한 질문은 서버가 로그인 안내로 돌려준다.
function ChatRoute() {
  const { user, isGuest } = useAuth()
  return (user || isGuest) ? <ChatPage /> : <Navigate to="/login" replace />
}

function AppRoutes() {
  const { user, isGuest } = useAuth()
  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/chat" replace /> : <LoginPage />} />
      <Route path="/signup" element={user ? <Navigate to="/chat" replace /> : <SignupPage />} />
      <Route path="/chat" element={<ChatRoute />} />
      <Route path="/admin" element={<ProtectedRoute><AdminPage /></ProtectedRoute>} />
      <Route path="/mypage" element={<ProtectedRoute><MyPage /></ProtectedRoute>} />
      <Route path="*" element={<Navigate to={(user || isGuest) ? '/chat' : '/login'} replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  )
}
