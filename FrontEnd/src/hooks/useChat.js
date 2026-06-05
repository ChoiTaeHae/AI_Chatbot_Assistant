import { useState, useCallback } from 'react'
import { sendMessage } from '../api/chat'

function getTime() {
  return new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
}

export function useChat() {
  const [messages, setMessages] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [sessionId, setSessionId] = useState(null)

  const send = useCallback(async (text) => {
    const userMsg = { id: Date.now(), role: 'user', content: text, time: getTime() }
    setMessages((prev) => [...prev, userMsg])
    setIsLoading(true)

    try {
      const data = await sendMessage(text, sessionId)
      if (data.session_id) setSessionId(data.session_id)
      const aiMsg = { id: Date.now() + 1, role: 'ai', content: data.answer, time: getTime() }
      setMessages((prev) => [...prev, aiMsg])
    } catch (err) {
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
  }, [sessionId])

  function reset() {
    setMessages([])
    setSessionId(null)
  }

  return { messages, isLoading, sessionId, send, reset }
}
