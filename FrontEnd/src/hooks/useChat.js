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
  const [pendingFile, setPendingFile] = useState(null)       // AI가 제안한 파일 { topic, filename }
  const [pendingContext, setPendingContext] = useState(null)  // 멀티턴 대화 상태 { type: "scholarship", ... }

  const send = useCallback(async (text) => {
    const userMsg = { id: Date.now(), role: 'user', content: text, time: getTime() }
    setMessages((prev) => [...prev, userMsg])
    setIsLoading(true)

    // 현재 pending 상태 캡처 (상태 변경 전에 사용)
    const currentPendingFile = pendingFile
    const currentPendingContext = pendingContext

    try {
      const data = await sendMessage(text, sessionId, currentPendingFile, currentPendingContext,lang)
      if (data.session_id) setSessionId(data.session_id)

      // pendingFile 상태 갱신
      if (data.file_download) {
        setPendingFile(null)
      } else if (data.file_offer) {
        // show_buttons=true면 버튼이 메시지에 표시되므로 pendingFile 제거
        // show_buttons=false면 사용자의 '응' 텍스트 응답 처리를 위해 유지
        if (data.file_offer.show_buttons) {
          setPendingFile(null)
        } else {
          setPendingFile(data.file_offer)
        }
      } else {
        setPendingFile(null)
      }

      // pendingContext 상태 갱신
      setPendingContext(data.pending_context || null)

      const aiMsg = {
        id: Date.now() + 1,
        role: 'ai',
        content: data.answer,
        time: getTime(),
        messageId: data.message_id || null,
        fileOffer: data.file_offer || null,        // { topic, files: [str] } 파일 선택 버튼용
        fileDownload: data.file_download || null,  // { topic, filename, url }
        mapCard: data.map_card || null,
      }
      setMessages((prev) => [...prev, aiMsg])
    } catch (err) {
      setPendingFile(null)
      const errMsg = {
        id: Date.now() + 1,
        role: 'ai',
        content: `${ERR[lang]}: ${err.message}`,
        time: getTime(),
      }
      setMessages((prev) => [...prev, errMsg])
    } finally {
      setIsLoading(false)
    }
  }, [sessionId, pendingFile, pendingContext, lang])
  
  function clearPendingFile() {
    setPendingFile(null)
  }

  function reset() {
    setMessages([])
    setSessionId(null)
    setPendingFile(null)
    setPendingContext(null)
  }

  return { messages, isLoading, sessionId, send, reset, clearPendingFile }
}
