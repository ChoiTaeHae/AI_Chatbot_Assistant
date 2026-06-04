import { createContext, useContext, useState } from 'react'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    const saved = sessionStorage.getItem('wsu_user')
    return saved ? JSON.parse(saved) : null
  })

  function saveUser(userData) {
    sessionStorage.setItem('wsu_user', JSON.stringify(userData))
    setUser(userData)
  }

  function clearUser() {
    sessionStorage.removeItem('wsu_user')
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
