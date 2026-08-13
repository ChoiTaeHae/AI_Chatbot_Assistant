import { useState, useCallback } from 'react'
import { sendMessage, getGraduationStatus, getSessionMessages } from '../api/chat'

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
  // 대화 전환(새 대화/과거 대화 열기)마다 증가 → ChatWindow를 remount해 '다른 창' 느낌을 준다.
  // (첫 메시지로 sessionId만 바뀔 땐 증가 안 함 → 대화 중엔 remount 안 됨)
  const [viewKey, setViewKey] = useState(0)

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
        scheduleCard: data.schedule_card || null,
        deptCard: data.dept_card || null,
        scholarshipCard: data.scholarship_card || null,
      }
      // [DEV-ONLY] rewrite가 있으면 사용자 메시지에 붙여 rewrite 피드백 패널 표시
      setMessages((prev) => {
        const withRewrite = data.rewritten_query
          ? prev.map((m) => (m.id === userMsg.id
              ? { ...m, rewrittenQuery: data.rewritten_query, rewriteMessageId: data.message_id || null }
              : m))
          : prev
        return [...withRewrite, aiMsg]
      })
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

    // 버튼 클릭은 대화가 아니라 동작이라 사용자 말풍선을 만들지 않는다.
    // ('네, 주세요!'를 대화로 남기면 다음 질문의 '이전 질문'이 되어 검색어 재작성을
    //  오염시킨다 — 예: '신청 가능해?' + 이전 '네, 주세요!' → 엉뚱한 검색어)
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
        scheduleCard: data.schedule_card || null,
        deptCard: data.dept_card || null,
        scholarshipCard: data.scholarship_card || null,
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

  /** '내 졸업 현황 보기' 버튼 — 개인 이수현황을 명시적으로 조회 (채팅 분류기 미경유) */
  const checkGraduation = useCallback(async () => {
    const userMsg = { id: Date.now(), role: 'user', content: '내 졸업 현황 보기', time: getTime() }
    setMessages((prev) => [...prev, userMsg])
    setIsLoading(true)
    try {
      const data = await getGraduationStatus()
      setMessages((prev) => [...prev, {
        id: Date.now() + 1,
        role: 'ai',
        content: data.answer,
        time: getTime(),
      }])
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
  }, [lang])

  /** 사이드바 '최근 대화'에서 과거 세션 다시 열기 */
  const loadSession = useCallback(async (sid) => {
    setIsLoading(true)
    setViewKey((k) => k + 1)   // 과거 대화 열기 → 뷰 새로 마운트
    try {
      const data = await getSessionMessages(sid)
      setSessionId(sid)
      setPendingFile(null)
      setPendingContext(null)
      setMessages((data.messages || []).map((m) => {
        // 답변에 딸렸던 카드(지도·학사일정·학과·파일제안) 복원 — 없으면 각 필드 null.
        const cm = m.card_meta || {}
        return {
          id: m.id,
          role: m.role === 'assistant' ? 'ai' : 'user',
          content: m.content,
          time: getTime(),
          messageId: m.message_id || null,
          mapCard: cm.map_card || null,
          scheduleCard: cm.schedule_card || null,
          deptCard: cm.dept_card || null,
          scholarshipCard: cm.scholarship_card || null,
          fileOffer: cm.file_offer || null,
        }
      }))
    } catch (err) {
      setMessages([{ id: Date.now(), role: 'ai', content: `${ERR[lang]}: ${err.message}`, time: getTime() }])
    } finally {
      setIsLoading(false)
    }
  }, [lang])

  /** 알림에서 고른 답변을 대화에 띄운다 (서버 호출 없음).
   *
   * 이미 확정된 문장이라 다시 물을 이유가 없다 — 같은 질문을 send()로 재전송하면 검색이
   * 한 번 더 돌고, 그 사이 FAQ 인덱스가 아직 안 잡히면 또 "찾지 못했어요"가 나와서
   * 알림을 눌렀는데 답이 없는 상황이 된다.
   *
   * DB에 남기지 않는 것은 의도다. 이건 새 대화가 아니라 '알림 열람'이라, 대화 기록에
   * 끼워 넣으면 다음 질문의 '이전 질문'이 되어 검색어 재작성을 오염시킨다
   * (파일 확인 버튼을 저장하지 않는 것과 같은 이유). 답변은 종 목록에 계속 남아 있으므로
   * 화면을 새로 고쳐도 다시 열어 볼 수 있다.
   */
  const pushAnswer = useCallback((question, answer) => {
    const now = Date.now()
    setMessages((prev) => [
      ...prev,
      { id: now, role: 'user', content: question, time: getTime() },
      { id: now + 1, role: 'ai', content: answer, time: getTime(), fromNotification: true },
    ])
  }, [])

  function clearPendingFile() {
    setPendingFile(null)
  }

  function reset() {
    setMessages([])
    setSessionId(null)
    setPendingFile(null)
    setPendingContext(null)
    setViewKey((k) => k + 1)   // 새 대화 → 뷰 새로 마운트
  }

  return { messages, isLoading, sessionId, send, confirmFile, checkGraduation, pushAnswer, reset, loadSession, clearPendingFile, pendingFile, viewKey }
}
