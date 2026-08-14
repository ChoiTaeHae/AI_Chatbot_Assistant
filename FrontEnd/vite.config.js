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

// 개발용 UI(재작성 라벨 패널 · 답변 평가 버튼)를 화면에 띄울지.
//
// .env.local을 쓰지 않는 이유 — docker-compose가 FrontEnd/src와 이 파일만 컨테이너에
// 마운트해서, 호스트에 .env.local을 만들어도 컨테이너 안에는 존재하지 않는다(실측).
// 이미 마운트된 이 파일에 두면 값을 바꾸고 컨테이너만 재시작하면 반영된다.
//
// 시연·발표 전에는 false. 평소 개발에서는 true로 두고 라벨을 수집한다.
// 복사 버튼은 이 스위치와 무관하다 — 개발용이 아니라 학생이 실제로 쓰는 기능이다.
// 프로덕션 빌드에서는 이 값과 관계없이 꺼진다(MessageBubble이 import.meta.env.DEV도 함께 본다).
const SHOW_DEV_TOOLS = false

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    'import.meta.env.VITE_SHOW_DEV_TOOLS': JSON.stringify(String(SHOW_DEV_TOOLS)),
  },
  server: {
    host: '0.0.0.0',
    // Windows 호스트를 컨테이너에 바인드 마운트하면 inotify 이벤트가 넘어오지 않는다.
    // → 파일을 고쳐도 Vite가 눈치채지 못해 HMR이 안 돌고, 새로고침해도 캐시된 옛 코드가
    //   계속 나온다(컨테이너를 재시작해야만 반영됨). 폴링으로 바꾸면 저장 즉시 반영된다.
    // 네이티브(npm run dev)는 inotify가 정상이라 폴링이 CPU만 축내므로,
    // docker-compose에서 VITE_USE_POLLING을 준 경우에만 켠다.
    watch: process.env.VITE_USE_POLLING
      ? { usePolling: true, interval: 300 }
      : undefined,
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
