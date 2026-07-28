// 다크/라이트 테마 헬퍼. data-theme 속성 + localStorage.
// 최초 적용은 index.html의 인라인 스크립트가 렌더 전에 처리(깜빡임 방지).

export function getTheme() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'
}

export function setTheme(t) {
  document.documentElement.setAttribute('data-theme', t)
  try { localStorage.setItem('theme', t) } catch (e) { /* ignore */ }
}

export function toggleTheme() {
  const next = getTheme() === 'dark' ? 'light' : 'dark'
  setTheme(next)
  return next
}
