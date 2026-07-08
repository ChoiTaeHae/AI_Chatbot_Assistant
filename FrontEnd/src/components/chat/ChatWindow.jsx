import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'
import LoadingDots from '../common/LoadingDots'
import MascotAvatar from '../common/MascotAvatar'

const T = {
  ko: { greeting: '안녕하세요! 무엇을 도와드릴까요? 👋', subtitle: '학사 관련 질문을 입력하면 AI가 답변해드립니다.', grad: '🎓 내 졸업 현황' },
  en: { greeting: 'Hello! How can I help you? 👋',       subtitle: 'Ask any academic questions and the AI will answer.', grad: '🎓 My Graduation Status' },
  zh: { greeting: '你好！有什么可以帮您？👋',                subtitle: '请输入与学业相관的问题，AI将为您解答。', grad: '🎓 我的毕业进度' },
}

export default function ChatWindow({ messages, isLoading, lang = 'ko', onClearPendingFile, pendingFile, onConfirmFile, onCheckGraduation }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  return (
    <section className="flex-1 overflow-y-auto bg-[#fdfdfd] flex flex-col items-center">
      <div className="w-full max-w-3xl" style={{ padding: '48px 20px 32px' }}>

        {/* 웰컴 메시지 (챗봇 말풍선 형태) + 내 졸업 현황 버튼 */}
        <div className="flex items-start gap-4" style={{ marginBottom: '24px', paddingLeft: '8px' }}>
          <MascotAvatar className="h-12 w-12 shrink-0 object-contain" style={{ marginTop: '4px' }} />
          <div style={{ flex: 1, maxWidth: '80%' }}>
            <div
              className="rounded-2xl rounded-tl-sm border border-slate-200 bg-white text-slate-800 shadow-sm"
              style={{ padding: '16px 20px', fontSize: '15px', lineHeight: '1.7' }}
            >
              <p className="font-bold text-slate-800">{T[lang].greeting}</p>
              <p className="text-sm text-slate-500" style={{ marginTop: '8px' }}>{T[lang].subtitle}</p>

              {/* 내 졸업 현황 버튼 */}
              <button
                onClick={onCheckGraduation}
                disabled={isLoading}
                className="text-xs font-semibold text-[#005956] border border-[#005956]/30 rounded-full hover:bg-[#005956]/5 transition disabled:opacity-50"
                style={{ padding: '8px 16px', marginTop: '24px' }}
              >
                {T[lang].grad}
              </button>
            </div>
          </div>
        </div>

        {/* 메시지 목록 */}
        {messages.map((msg, index) => (
          <MessageBubble 
            key={msg.id} 
            message={msg} 
            onClearPendingFile={onClearPendingFile} 
            pendingFile={pendingFile}
            onConfirmFile={onConfirmFile}
            isLatest={index === messages.length - 1}
          />
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