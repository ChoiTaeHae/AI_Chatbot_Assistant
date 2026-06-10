/**
 * 인증 토큰을 자동으로 헤더에 추가하는 fetch 래퍼
 * API 함수에서 fetch 대신 authFetch 를 사용하면 됨
 */
const TOKEN_KEY = 'wsu_token'

export function authFetch(url, options = {}) {
  const token = sessionStorage.getItem(TOKEN_KEY)
  const headers = {
    ...options.headers,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
  return fetch(url, { ...options, headers })
}
