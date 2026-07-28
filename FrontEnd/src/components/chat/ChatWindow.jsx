import { useEffect, useRef } from 'react'
import MessageBubble from './MessageBubble'
import LoadingDots from '../common/LoadingDots'
import MascotAvatar from '../common/MascotAvatar'

const T = {
  ko: { greeting: '안녕하세요! 무엇을 도와드릴까요? 👋', subtitle: '학사 관련 질문을 입력하면 AI가 답변해드립니다.', grad: '내 졸업 현황',
        chips: ['휴학 어떻게 신청해?', '학생회관 어디야?', '장학금 뭐 있어?'] },
  en: { greeting: 'Hello! How can I help you? 👋',       subtitle: 'Ask any academic questions and the AI will answer.', grad: 'My Graduation Status',
        chips: ['How do I apply for a leave of absence?', 'Where is the Student Union?', 'What scholarships are available?'] },
  zh: { greeting: '你好！有什么可以帮您？👋',                subtitle: '请输入与学业相관的问题，AI将为您解答。', grad: '我的毕业进度',
        chips: ['如何申请休学？', '学生会馆在哪里？', '有哪些奖学金？'] },
}

export default function ChatWindow({ messages, isLoading, lang = 'ko', onClearPendingFile, pendingFile, onConfirmFile, onCheckGraduation, onSendQuestion }) {
  const bottomRef = useRef(null)
  const firstScroll = useRef(true)   // 마운트 직후 첫 스크롤은 즉시(대화 전환 시 스무스 스크롤 튐 방지)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: firstScroll.current ? 'auto' : 'smooth' })
    firstScroll.current = false
  }, [messages, isLoading])

  return (
    <section className="flex-1 overflow-y-auto bg-(--surface-card) flex flex-col items-center chat-view-enter">
      {messages.length === 0 ? (
        /* 시작 화면 — 중앙 정렬 인사 + 질문칩 */
        <div className="flex-1 w-full max-w-3xl flex flex-col items-center justify-center" style={{ padding: '24px' }}>
          <div className="flex flex-col items-center text-center w-full" style={{ maxWidth: '420px' }}>
            {/* MascotAvatar가 style prop을 안 받으므로 여백은 wrapper로 처리 */}
            <div style={{ marginBottom: '18px' }}>
              <MascotAvatar className="h-[124px] w-[124px] object-contain" />
            </div>
            <p className="font-bold text-(--text)" style={{ fontSize: '24px' }}>{T[lang].greeting}</p>
            <p className="text-(--text-muted)" style={{ marginTop: '9px', fontSize: '15px' }}>{T[lang].subtitle}</p>

            {/* 추천 질문 칩 (2x2 균일 그리드) — 졸업 현황도 동일 스타일로 통일 */}
            <div className="grid grid-cols-2 gap-3.5 w-full" style={{ marginTop: '26px' }}>
              {[...T[lang].chips, T[lang].grad].map((label) => (
                <button
                  key={label}
                  onClick={() => (label === T[lang].grad ? onCheckGraduation?.() : onSendQuestion?.(label))}
                  disabled={isLoading}
                  className="w-full flex items-center justify-center text-center font-medium text-(--text-muted) border border-(--border) rounded-full hover:border-(--brand-a40) hover:text-(--brand) hover:bg-(--brand-a5) transition disabled:opacity-50"
                  style={{ minHeight: '44px', padding: '9px 18px', fontSize: '15px' }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        /* 대화 화면 */
        <div className="w-full max-w-3xl" style={{ padding: '32px 20px' }}>
          {/* 대화 중에도 상단 인사 말풍선 유지 — 첫 메시지 후 휑해 보이지 않도록 */}
          <div className="flex items-start gap-4" style={{ marginBottom: '20px', paddingLeft: '8px' }}>
            <MascotAvatar className="h-12 w-12 shrink-0 object-contain mt-1" />
            <div className="rounded-2xl rounded-tl-sm border border-(--border) bg-(--surface-card) shadow-sm" style={{ padding: '14px 18px', maxWidth: '80%' }}>
              <p className="font-bold text-(--text)" style={{ fontSize: '15px' }}>{T[lang].greeting}</p>
              <p className="text-(--text-muted)" style={{ marginTop: '4px', fontSize: '13px' }}>{T[lang].subtitle}</p>
            </div>
          </div>

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
              <div className="rounded-2xl rounded-tl-sm border border-(--border) bg-(--surface-card) px-5 py-4 shadow-sm">
                <LoadingDots />
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      )}
    </section>
  )
}