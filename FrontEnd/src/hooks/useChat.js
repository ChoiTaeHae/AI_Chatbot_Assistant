import { useState, useCallback } from 'react'
import { sendMessage } from '../api/chat'

function getTime() {
  return new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
}

export function useChat() {
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
      const data = await sendMessage(text, sessionId, currentPendingFile, currentPendingContext)
      if (data.session_id) setSessionId(data.session_id)

      // pendingFile 상태 갱신
      if (data.file_download) {
        setPendingFile(null)
      } else if (data.file_offer) {
        setPendingFile(data.file_offer)
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
        fileDownload: data.file_download || null, // { topic, filename, url }
        mapCard: data.map_card || null,           // { title, address, place_url, latitude, longitude }
      }
      setMessages((prev) => [...prev, aiMsg])
    } catch (err) {
      setPendingFile(null)
      const errMsg = {
        id: Date.now() + 1,
        role: 'ai',
        content: `오류가 발생했습니다: ${err.message}`,
        time: getTime(),
      }
      setMessages((prev) => [...prev, errMsg])
    } finally {
      setIsLoading(false)
    }
  }, [sessionId, pendingFile, pendingContext])

  function reset() {
    setMessages([])
    setSessionId(null)
    setPendingFile(null)
    setPendingContext(null)
  }

  return { messages, isLoading, sessionId, send, reset }
}
