import { useState } from 'react'
import { answerUnanswered } from '../../api/admins/faq'
import { BTN, BTN_PAD_LG } from './buttonStyles'

/* 미답변 질문에 답변을 작성해 FAQ로 등록하는 모달.
 *
 * 별도 컴포넌트로 뺀 이유 — 미답변 목록(UnansweredManager)과 헤더 알림 팝업(NotificationPanel)
 * 두 곳에서 같은 폼을 쓴다. 복사해 두면 한쪽만 고쳐져 두 화면의 동작이 갈라진다.
 *
 * 여백은 전역 `* { padding: 0 }` 리셋이 Tailwind 유틸을 덮어써서 인라인 style로 준다.
 */
export default function UnansweredAnswerModal({ row, onClose, onSaved }) {
  const [answer, setAnswer] = useState('')
  const [variants, setVariants] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  async function submit() {
    if (!answer.trim()) { setError('답변 내용을 입력하세요.'); return }
    setSaving(true); setError(null)
    try {
      // 한 줄 = 한 변형. 빈 줄은 버린다.
      const list = variants.split('\n').map((s) => s.trim()).filter(Boolean)
      const r = await answerUnanswered(row.id, answer.trim(), list)
      onSaved?.(r)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const cardCls = 'bg-(--surface-card) rounded-2xl shadow-sm border border-(--border)'
  const inputCls = 'w-full border border-(--border) rounded-xl text-(--text) bg-(--surface-card) outline-none focus:border-(--brand) transition'
  const inputStyle = { padding: '10px 12px', fontSize: '14px' }

  return (
    /* data-answer-modal — 헤더 알림 팝업의 '바깥 클릭 시 닫기'가 이 모달 클릭을 바깥으로
       보고 팝업을 닫아 버리는 것을 막는 표시다(AdminPage handleClickOutside에서 확인). */
    <div data-answer-modal
         className="fixed inset-0 z-[60] flex items-center justify-center"
         style={{ background: 'rgba(0,0,0,.45)', padding: '20px' }}
         onMouseDown={() => !saving && onClose?.()}>
      <div className={cardCls}
           onMouseDown={(e) => e.stopPropagation()}
           style={{ padding: '24px 26px', width: '100%', maxWidth: '620px',
                    maxHeight: '86vh', overflowY: 'auto' }}>
        <h3 className="font-black text-(--text)" style={{ fontSize: '15px' }}>답변 작성</h3>

        <div className="rounded-xl" style={{ padding: '12px 14px', marginTop: '14px',
                                             background: 'var(--surface-2)' }}>
          <p className="text-xs text-(--text-muted)">학생 질문</p>
          <p className="text-sm text-(--text)" style={{ marginTop: '4px' }}>{row.question}</p>
          {/* 왜 못 찾았는지가 보여야 답변을 제대로 쓸 수 있다. 토픽이 엉뚱하면
              FAQ가 아니라 라우팅 문제라는 신호이기도 하다. */}
          <div className="flex flex-wrap text-xs text-(--text-faint)"
               style={{ gap: '8px', marginTop: '6px' }}>
            {row.topic && <span>토픽 {row.topic}</span>}
            {row.rewritten && <span>· 검색어 “{row.rewritten}”</span>}
            {row.occurrences > 1 && <span>· {row.occurrences}회 질문됨</span>}
          </div>
        </div>

        <label className="flex flex-col" style={{ gap: '6px', marginTop: '16px' }}>
          <span className="text-xs font-bold text-(--text-muted)">답변</span>
          <textarea rows={6} className={inputCls} style={{ ...inputStyle, resize: 'vertical' }}
            value={answer} onChange={(e) => setAnswer(e.target.value)}
            placeholder="학생에게 그대로 나갈 문장입니다. 확인된 사실만 적어 주세요." />
        </label>

        <label className="flex flex-col" style={{ gap: '6px', marginTop: '14px' }}>
          <span className="text-xs font-bold text-(--text-muted)">
            질문 변형 <span className="font-normal text-(--text-faint)">(한 줄에 하나)</span>
          </span>
          <textarea rows={4} className={inputCls} style={{ ...inputStyle, resize: 'vertical' }}
            value={variants} onChange={(e) => setVariants(e.target.value)}
            placeholder={'상담 어디서 해?\n심리상담 신청 방법\n학생상담센터 위치'} />
          <span className="text-xs text-(--text-faint)" style={{ lineHeight: 1.5 }}>
            학생은 등록된 문장 그대로 묻지 않습니다. 표현을 바꾼 질문을 2~3개 더 넣어야
            다음에 다르게 물어도 같은 답변이 나갑니다.
          </span>
        </label>

        {error && (
          <p className="text-xs font-bold" style={{ marginTop: '12px', color: 'var(--danger-text)' }}>
            {error}
          </p>
        )}

        <div className="flex justify-end" style={{ gap: '8px', marginTop: '20px' }}>
          <button onClick={() => onClose?.()} disabled={saving}
            className={BTN.tabOff} style={BTN_PAD_LG}>
            취소
          </button>
          <button onClick={submit} disabled={saving}
            className={BTN.primary} style={BTN_PAD_LG}>
            {saving ? '등록 중...' : 'FAQ로 등록'}
          </button>
        </div>
      </div>
    </div>
  )
}
