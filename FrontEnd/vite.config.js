import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 프론트는 API를 상대경로(/api)로 호출한다. dev 서버가 이를 백엔드로 프록시하므로
// 브라우저 입장에선 프론트와 API가 같은 origin이다 → CORS 불필요, 외부 공개 시에도
// 프론트 하나(터널 URL)만 노출하면 API까지 동작한다.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    // Cloudflare Tunnel 등 외부 호스트에서 접속 허용(임시 URL이 매번 바뀌므로 전체 허용).
    // 시연용 설정 — 상시 서비스로 갈 땐 특정 도메인만 허용하도록 좁힌다.
    allowedHosts: true,
    proxy: {
      // 같은 compose 네트워크의 backend 컨테이너로 넘긴다.
      '/api': { target: 'http://backend:8000', changeOrigin: true },
      '/health': { target: 'http://backend:8000', changeOrigin: true },
    },
  },
})
