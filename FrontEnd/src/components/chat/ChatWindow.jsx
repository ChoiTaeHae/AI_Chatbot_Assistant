import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'
import LoadingDots from '../common/LoadingDots'
import MascotAvatar from '../common/MascotAvatar'

const T = {
  ko: { greeting: '안녕하세요! 무엇을 도와드릴까요? 👋', subtitle: '학사 관련 질문을 입력하면 AI가 답변해드립니다.' },
  en: { greeting: 'Hello! How can I help you? 👋',       subtitle: 'Ask any academic questions and the AI will answer.' },
  zh: { greeting: '你好！有什么可以帮您？👋',                subtitle: '请输入与学业相관的问题，AI将为您解答。' },
}

export default function ChatWindow({ messages, isLoading, lang = 'ko', onClearPendingFile }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  return (
    <section className="flex-1 overflow-y-auto bg-[#fdfdfd] flex flex-col items-center">
      <div className="w-full max-w-2xl" style={{ padding: '40px 32px' }}>

        {/* 웰컴 헤더 (말풍선 밖으로 뺌) */}
        <div className="mb-12 mt-4 px-4">
          <h2 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
            {T[lang].greeting}
          </h2>
          <p className="mt-3 text-base text-slate-500">
            {T[lang].subtitle}
          </p>
        </div>

        {/* 메시지 목록 */}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} onClearPendingFile={onClearPendingFile} />
        ))}

        {/* 로딩 */}
        {isLoading && (
          <div className="flex items-start gap-4 mb-8 pl-4">
            <MascotAvatar className="h-12 w-12 shrink-0 object-contain mt-1" />
            <div className="rounded-2xl rounded-tl-sm border border-slate-200 bg-white px-5 py-4 shadow-sm">
              <LoadingDots />
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </section>
  )
}