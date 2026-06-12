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
  const [pendingFile, setPendingFile] = useState(null) // AI가 제안한 파일 { topic, filename }

  const send = useCallback(async (text) => {
    const userMsg = { id: Date.now(), role: 'user', content: text, time: getTime() }
    setMessages((prev) => [...prev, userMsg])
    setIsLoading(true)

    // 현재 pendingFile 캡처 (상태 변경 전에 사용)
    const currentPendingFile = pendingFile

    try {
      const data = await sendMessage(text, sessionId, currentPendingFile, lang)
      if (data.session_id) setSessionId(data.session_id)

      // pendingFile 상태 갱신
      if (data.file_download) {
        // 파일이 실제로 전송됨 → 초기화
        setPendingFile(null)
      } else if (data.file_offer) {
        // AI가 새 파일 제안 → 갱신 (다음 메시지에서 pending_file로 전달)
        setPendingFile(data.file_offer)
      } else {
        // 다른 주제로 넘어감 → 초기화
        setPendingFile(null)
      }

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
        content: `${ERR[lang]}: ${err.message}`,
        time: getTime(),
      }
      setMessages((prev) => [...prev, errMsg])
    } finally {
      setIsLoading(false)
    }
  }, [sessionId, pendingFile, lang])

  function reset() {
    setMessages([])
    setSessionId(null)
    setPendingFile(null)
  }

  return { messages, isLoading, sessionId, send, reset }
}
