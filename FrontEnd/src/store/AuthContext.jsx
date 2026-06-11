import { createContext, useContext, useState } from 'react'

const AuthContext = createContext(null)

const TOKEN_KEY = 'wsu_token'
const USER_KEY  = 'wsu_user'

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const saved = sessionStorage.getItem(USER_KEY)
    return saved ? JSON.parse(saved) : null
  })

  function saveUser(userData) {
    const { access_token, token_type, ...userInfo } = userData
    if (access_token) {
      sessionStorage.setItem(TOKEN_KEY, access_token)
    }
    sessionStorage.setItem(USER_KEY, JSON.stringify(userInfo))
    setUser(userInfo)
  }

  function clearUser() {
    sessionStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem(USER_KEY)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, saveUser, clearUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
