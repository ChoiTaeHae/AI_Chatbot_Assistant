import { createContext, useContext, useState, useCallback } from 'react'

const AuthContext = createContext(null)

const TOKEN_KEY = 'wsu_token'
const USER_KEY  = 'wsu_user'
const GUEST_KEY = 'wsu_guest'   // '둘러보기'로 들어왔다는 표시 (새로고침해도 /login으로 튕기지 않게)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const saved = sessionStorage.getItem(USER_KEY)
    return saved ? JSON.parse(saved) : null
  })

  // 로그인하지 않고 둘러보는 중인가. user가 있으면 언제나 false다
  // (로그인하면 게스트 상태는 의미가 없어지므로 saveUser에서 지운다).
  const [isGuest, setIsGuest] = useState(
    () => !sessionStorage.getItem(USER_KEY) && sessionStorage.getItem(GUEST_KEY) === '1'
  )

  // 게스트가 로그인 필요한 기능을 눌렀을 때 띄우는 안내. { feature: '내 성적' } 형태.
  // 화면마다 모달을 따로 만들지 않고 App에서 하나만 렌더한다 — 문구와 동작이 갈리지 않게.
  const [loginPrompt, setLoginPrompt] = useState(null)

  function saveUser(userData) {
    const { access_token, token_type, ...userInfo } = userData
    if (access_token) {
      sessionStorage.setItem(TOKEN_KEY, access_token)
    }
    sessionStorage.setItem(USER_KEY, JSON.stringify(userInfo))
    sessionStorage.removeItem(GUEST_KEY)
    setIsGuest(false)
    setLoginPrompt(null)
    setUser(userInfo)
  }

  function clearUser() {
    sessionStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem(USER_KEY)
    sessionStorage.removeItem(GUEST_KEY)
    setIsGuest(false)
    setLoginPrompt(null)
    setUser(null)
  }

  function enterGuest() {
    sessionStorage.setItem(GUEST_KEY, '1')
    setIsGuest(true)
  }

  /** 로그인이 필요한 기능을 게스트가 눌렀을 때. feature는 안내 문구에 그대로 들어간다. */
  const requireLogin = useCallback((feature) => {
    setLoginPrompt({ feature: feature || '이 기능' })
  }, [])

  const closeLoginPrompt = useCallback(() => setLoginPrompt(null), [])

  return (
    <AuthContext.Provider value={{
      user, saveUser, clearUser,
      isGuest, enterGuest,
      loginPrompt, requireLogin, closeLoginPrompt,
    }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
