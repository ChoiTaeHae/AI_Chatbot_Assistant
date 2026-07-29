import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 프론트는 API를 상대경로(/api)로 호출한다. dev 서버가 이를 백엔드로 프록시하므로
// 브라우저 입장에선 프론트와 API가 같은 origin이다 → CORS 불필요, 외부 공개 시에도
// 프론트 하나(터널 URL)만 노출하면 API까지 동작한다.

// 백엔드가 아직 안 떴거나 죽었을 때 http-proxy가 요청마다 ECONNREFUSED 스택트레이스를
// 쏟아내는 걸 막는다 — 스택 대신 한 줄 경고만 찍고(60초 스로틀) 브라우저엔 502를 돌려준다.
// 백엔드가 다운됐다는 신호는 남기되 콘솔 노이즈만 죽이는 목적.
let lastWarn = 0
function quietProxy(proxy) {
  proxy.on('error', (err, _req, res) => {
    const now = Date.now()
    if (now - lastWarn > 60000) {
      console.warn(`[proxy] 백엔드(backend:8000) 연결 안 됨 (${err.code || err.message}). 백엔드 컨테이너 상태 확인 필요.`)
      lastWarn = now
    }
    if (res && !res.headersSent && res.writeHead) {
      res.writeHead(502, { 'Content-Type': 'application/json' })
      res.end('{"detail":"backend unavailable"}')
    }
  })
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    // Cloudflare Tunnel 등 외부 호스트에서 접속 허용(임시 URL이 매번 바뀌므로 전체 허용).
    // 시연용 설정 — 상시 서비스로 갈 땐 특정 도메인만 허용하도록 좁힌다.
    allowedHosts: true,
    proxy: {
      // 같은 compose 네트워크의 backend 컨테이너로 넘긴다.
      '/api': { target: 'http://backend:8000', changeOrigin: true, configure: quietProxy },
      '/health': { target: 'http://backend:8000', changeOrigin: true, configure: quietProxy },
    },
  },
})
