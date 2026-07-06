import { useState, useCallback } from 'react'
import { sendMessage } from '../api/chat'

function getTime() {
  return new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
}

const ERR = {
  ko: '오류가 발생했습니다',
  en: 'An error occurred',
  zh: '发生了错误',
}

export function useChat(lang = 'ko') {
  const [messages, setMessages] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId, setSessionId] = useState(null)
  const [pendingFile, setPendingFile] = useState(null)       // AI가 제안한 파일 { topic, files }
  const [pendingContext, setPendingContext] = useState(null)  // 멀티턴 대화 상태 { type: "scholarship", ... }

  /** 일반 메시지 전송 */
  const send = useCallback(async (text) => {
    const userMsg = { id: Date.now(), role: 'user', content: text, time: getTime() }
    setMessages((prev) => [...prev, userMsg])
    setIsLoading(true)

    const currentPendingContext = pendingContext

    try {
      // 일반 질문: file_confirm 없이 전송 (파일 제안 상태는 버튼으로만 처리)
      const data = await sendMessage(text, sessionId, null, currentPendingContext, lang)
      if (data.session_id) setSessionId(data.session_id)

      // 새 파일 제안이 오면 pendingFile 저장
      if (data.file_offer && !data.file_offer.show_buttons) {
        setPendingFile(data.file_offer)
      } else {
        setPendingFile(null)
      }

      setPendingContext(data.pending_context || null)

      const aiMsg = {
        id: Date.now() + 1,
        role: 'ai',
        content: data.answer,
        time: getTime(),
        messageId: data.message_id || null,
        fileOffer: data.file_offer || null,
        fileDownload: data.file_download || null,
        mapCard: data.map_card || null,
      }
      setMessages((prev) => [...prev, aiMsg])
    } catch (err) {
      setPendingFile(null)
      setMessages((prev) => [...prev, {
        id: Date.now() + 1,
        role: 'ai',
        content: `${ERR[lang]}: ${err.message}`,
        time: getTime(),
      }])
    } finally {
      setIsLoading(false)
    }
  }, [sessionId, pendingContext, lang])

  /** 예/아니오 버튼 클릭 시 호출 */
  const confirmFile = useCallback(async (fileOffer, confirmed) => {
    setIsLoading(true)
    const currentPendingFile = fileOffer

    // 사용자 버튼 클릭을 채팅 메시지로 표시
    const userMsg = {
      id: Date.now(),
      role: 'user',
      content: confirmed ? '네, 주세요!' : '아니요, 괜찮습니다.',
      time: getTime(),
    }
    setMessages((prev) => [...prev, userMsg])
    setPendingFile(null)

    try {
      const data = await sendMessage(
        confirmed ? '네' : '아니요',
        sessionId,
        currentPendingFile,
        pendingContext,
        lang,
        confirmed,          // file_confirm
      )
      if (data.session_id) setSessionId(data.session_id)

      // 파일 2개 이상 확인 시 버튼 표시 상태
      if (data.file_offer?.show_buttons) {
        setPendingFile(null)
      } else if (data.file_offer) {
        setPendingFile(data.file_offer)
      } else {
        setPendingFile(null)
      }

      setPendingContext(data.pending_context || null)

      const aiMsg = {
        id: Date.now() + 1,
        role: 'ai',
        content: data.answer,
        time: getTime(),
        messageId: data.message_id || null,
        fileOffer: data.file_offer || null,
        fileDownload: data.file_download || null,
        mapCard: data.map_card || null,
      }
      setMessages((prev) => [...prev, aiMsg])
    } catch (err) {
      setMessages((prev) => [...prev, {
        id: Date.now() + 1,
        role: 'ai',
        content: `${ERR[lang]}: ${err.message}`,
        time: getTime(),
      }])
    } finally {
      setIsLoading(false)
    }
  }, [sessionId, pendingContext, lang])

  function clearPendingFile() {
    setPendingFile(null)
  }

  function reset() {
    setMessages([])
    setSessionId(null)
    setPendingFile(null)
    setPendingContext(null)
  }

  return { messages, isLoading, sessionId, send, confirmFile, reset, clearPendingFile, pendingFile }
}
