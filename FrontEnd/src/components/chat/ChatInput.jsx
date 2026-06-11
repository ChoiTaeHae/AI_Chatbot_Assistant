import { useEffect, useRef, useState } from 'react'

const MAX_LENGTH = 1000

export default function ChatInput({ onSend, disabled }) {
  const [text, setText] = useState('')
  const textareaRef = useRef(null)

  useEffect(() => {
    if (!disabled) {
      textareaRef.current?.focus()
    }
  }, [disabled])

  function handleSubmit(e) {
    e.preventDefault()
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText('')
    textareaRef.current?.focus()
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <div style={{ flexShrink: 0, background: '#fff', padding: '10px 16px 16px' }}>
      <form onSubmit={handleSubmit}>
        <div style={{ position: 'relative', borderRadius: '16px', border: '1px solid #e2e8f0', background: '#fff', padding: '10px 14px', boxShadow: '0 2px 8px -4px rgba(0,0,0,0.06)' }}>
          <textarea
            ref={textareaRef}
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, MAX_LENGTH))}
            onKeyDown={handleKeyDown}
            placeholder="메시지를 입력하세요..."
            disabled={disabled}
            rows={2}
            style={{
              width: '100%',
              resize: 'none',
              background: 'transparent',
              fontSize: '14px',
              fontWeight: 500,
              lineHeight: '1.5',
              color: '#1e293b',
              outline: 'none',
              paddingLeft: '4px',
              paddingRight: '44px',
              paddingTop: '2px',
              maxHeight: '110px',
              opacity: disabled ? 0.5 : 1,
            }}
            onInput={(e) => {
              e.target.style.height = 'auto'
              e.target.style.height = Math.min(e.target.scrollHeight, 110) + 'px'
            }}
          />
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingLeft: '4px', marginTop: '-4px' }}>
            <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 500 }}>{text.length} / {MAX_LENGTH}</span>
            <button
              type="submit"
              disabled={!text.trim() || disabled}
              style={{
                position: 'absolute',
                right: '12px',
                bottom: '10px',
                height: '34px',
                width: '34px',
                borderRadius: '50%',
                background: '#004d4a',
                color: '#fff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                cursor: !text.trim() || disabled ? 'not-allowed' : 'pointer',
                opacity: !text.trim() || disabled ? 0.4 : 1,
                border: 'none',
                boxShadow: '0 1px 4px rgba(0,0,0,0.15)',
                transition: 'background 0.15s',
              }}
            >
              <svg style={{ height: '16px', width: '16px', marginLeft: '2px' }} viewBox="0 0 24 24" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
              </svg>
            </button>
          </div>
        </div>
        <p style={{ marginTop: '8px', textAlign: 'center', fontSize: '11px', color: '#94a3b8' }}>
          AI의 답변은 참고용이며, 정확한 정보는 공식 문서를 확인해주세요.
        </p>
      </form>
    </div>
  )
}
