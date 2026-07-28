import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

// 테마 초기화 — React 마운트 전에 data-theme 적용 (저장값 → 없으면 시스템 설정)
;(function initTheme() {
  try {
    let t = localStorage.getItem('theme')
    if (t !== 'dark' && t !== 'light') {
      t = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    }
    document.documentElement.setAttribute('data-theme', t)
  } catch (e) { /* ignore */ }
})()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
