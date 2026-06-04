import { useState } from 'react'

const MAX_LENGTH = 1000

export default function ChatInput({ onSend, disabled }) {
  const [text, setText] = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText('')
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <div className="shrink-0 bg-white px-8 pb-8 pt-4 flex justify-center">
      <form onSubmit={handleSubmit} className="w-full max-w-2xl">
        <div className="relative rounded-2xl border border-slate-200 bg-white px-6 py-4 shadow-[0_2px_10px_-4px_rgba(0,0,0,0.05)] focus-within:border-[#004d4a] focus-within:ring-1 focus-within:ring-[#004d4a] transition">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value.slice(0, MAX_LENGTH))}
            onKeyDown={handleKeyDown}
            placeholder="메시지를 입력하세요..."
            disabled={disabled}
            rows={2}
            className="w-full resize-none bg-transparent text-[15px] font-medium leading-6 text-slate-800 outline-none placeholder:text-slate-400 disabled:opacity-50"
            style={{ maxHeight: '140px', paddingLeft: '12px', paddingRight: '56px', paddingTop: '8px' }}
            onInput={(e) => {
              e.target.style.height = 'auto'
              e.target.style.height = Math.min(e.target.scrollHeight, 140) + 'px'
            }}
          />
          <div className="flex items-center justify-between mt-2" style={{ paddingLeft: '12px', marginTop: '-8px' }}>
            <span className="text-xs text-slate-400 font-medium">{text.length} / {MAX_LENGTH}</span>
            <button
              type="submit"
              disabled={!text.trim() || disabled}
              // 배경색을 짙은 녹색으로 변경, 둥근 형태 유지
              className="h-10 w-10 rounded-full bg-[#004d4a] text-white flex items-center justify-center hover:bg-[#003634] disabled:opacity-40 disabled:cursor-not-allowed transition shadow-sm absolute right-6 bottom-4"
            >
              {/* 종이비행기 아이콘 (Filled) */}
              <svg className="h-5 w-5 ml-1" viewBox="0 0 24 24" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
              </svg>
            </button>
          </div>
        </div>
        <p className="mt-4 text-center text-[13px] text-slate-400">
          AI의 답변은 참고용이며, 정확한 정보는 공식 문서를 확인해주세요.
        </p>
      </form>
    </div>
  )
}