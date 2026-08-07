/* 화면 아래에 잠깐 뜨는 알림.
 *
 * 카드 안에 글자로 띄우면 나타나고 사라질 때마다 아래 내용이 밀려 화면이 흔들린다.
 * 문서 흐름 밖(fixed)에 띄워 레이아웃을 건드리지 않는다.
 *
 * 오류는 이걸로 띄우지 않는다 — 오류는 어느 입력이 문제인지 옆에 붙어 있어야 하고,
 * 시간이 지나 사라지면 안 된다. 여기 tone='error'는 '되돌릴 수 없는 동작이 실패했다'처럼
 * 특정 입력에 매어 있지 않은 경우에만 쓴다.
 *
 * 여백은 전역 `* { padding: 0 }` 리셋이 Tailwind 유틸을 덮어써서 인라인 style로 준다.
 */
export default function Toast({ message, tone = 'ok' }) {
  if (!message) return null
  return (
    <div role="status" aria-live="polite"
         className="fixed inset-x-0 flex justify-center chat-view-enter"
         style={{ bottom: '24px', zIndex: 60, pointerEvents: 'none', padding: '0 16px' }}>
      <div className="rounded-xl shadow-lg font-bold text-white"
           style={{
             padding: '11px 18px', fontSize: '13px', lineHeight: 1.5,
             background: tone === 'error' ? '#dc2626' : 'var(--brand)',
           }}>
        {message}
      </div>
    </div>
  )
}
