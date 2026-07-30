import { useState } from 'react'
import { matchScholarships } from '../../api/scholarship'

const TEAL = 'var(--brand)'

// 시/도 (본인·부모 거주지). 빈 값 = 선택 안 함(무관)
const REGIONS = [
  '', '서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
  '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주',
]
// 소득 구간 — value는 백엔드 매칭 코드, label은 표시
const INCOMES = [
  { v: '', label: '해당없음 · 모름' },
  { v: '기초', label: '기초생활수급' },
  { v: '차상위', label: '차상위계층' },
  { v: '중위100', label: '중위소득 100% 이하' },
  { v: '중위200', label: '중위소득 100~200%' },
]
// 관심 유형 — 카탈로그의 실제 카테고리(선택 시 결과에서 앞으로 정렬)
const INTERESTS = [
  '학업지원금(생활비)', '지자체', '학업장려금', '우수인재',
  '학회·연구지원', '인재육성', '주거복지(주거지원) 장학금', '취·창업지원형', '취업연계형',
]
// 예/아니오 토글 항목
const FLAGS = [
  ['multichild', '다자녀 가정'],
  ['foreigner', '외국인 · 유학생'],
  ['independent', '자취 · 독립 거주'],
  ['disabled', '장애'],
  ['veteran', '보훈 · 국가유공자(후손)'],
]

const majorFieldLabel = (f) => ({ 인문사회: '인문·사회', 예술체육: '예술·체육', 이공: '이공' }[f] || f || '-')

export default function ScholarshipSurveyModal({ onClose, onPick }) {
  const [step, setStep] = useState('form')   // 'form' | 'result'
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)  // { count, items, profile }

  const [a, setA] = useState({
    self_region: '', parent_region: '', income: '', interests: [], age: '',
    multichild: false, foreigner: false, independent: false, disabled: false, veteran: false,
  })
  const set = (k, v) => setA((p) => ({ ...p, [k]: v }))
  const toggleInterest = (c) =>
    setA((p) => ({ ...p, interests: p.interests.includes(c) ? p.interests.filter((x) => x !== c) : [...p.interests, c] }))

  async function submit() {
    setLoading(true); setError(null)
    try {
      const payload = { ...a, age: a.age ? Number(a.age) : null }
      const res = await matchScholarships(payload)
      setResult(res)
      setStep('result')
    } catch (e) {
      setError(e.message)
    } finally { setLoading(false) }
  }

  const selectCls = 'w-full text-sm text-(--text) border border-(--modal-edge) rounded-lg bg-(--surface-2) outline-none focus:border-(--brand)'
  const p = result?.profile

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'var(--scrim)', padding: '16px' }} onClick={onClose}>
      <div
        className="bg-(--surface-modal) rounded-2xl shadow-2xl border border-(--modal-edge) overflow-hidden flex flex-col"
        style={{ width: '100%', maxWidth: '560px', height: '84vh', maxHeight: '720px' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="flex items-center gap-3 border-b border-(--border) shrink-0" style={{ padding: '16px 18px' }}>
          <div className="flex items-center justify-center rounded-lg shrink-0" style={{ width: '34px', height: '34px', background: TEAL }}>
            <span className="emoji" style={{ fontSize: '18px' }}>🎯</span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-bold text-(--text)" style={{ fontSize: '15px' }}>맞춤 장학금 찾기</p>
            <p className="text-(--text-faint)" style={{ fontSize: '12px' }}>
              {step === 'form' ? '몇 가지만 알려주시면 맞는 장학금을 찾아드려요' : `조건에 맞는 장학금 ${result?.count ?? 0}건`}
            </p>
          </div>
          <button onClick={onClose} className="text-(--text-faint) hover:text-(--text-body) text-lg" aria-label="닫기">✕</button>
        </div>

        {step === 'form' ? (
          <>
            <div style={{ padding: '16px 18px', overflowY: 'auto' }} className="flex-1">
              {/* 자동 연동 안내 */}
              <div className="rounded-lg" style={{ background: 'var(--brand-tint)', padding: '9px 12px', marginBottom: '16px' }}>
                <p className="text-(--text-muted)" style={{ fontSize: '12px' }}>
                  <span className="emoji">🔗</span> 성적 · 학년 · 전공은 <b>내 정보에서 자동 연동</b>돼요.
                </p>
              </div>

              <div className="grid grid-cols-2" style={{ gap: '14px' }}>
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-bold text-(--text-muted)">본인 거주 지역</span>
                  <select className={selectCls} style={{ padding: '8px 10px' }} value={a.self_region} onChange={(e) => set('self_region', e.target.value)}>
                    {REGIONS.map((r) => <option key={r || 'none'} value={r}>{r || '선택 안 함'}</option>)}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-bold text-(--text-muted)">부모님 거주 지역</span>
                  <select className={selectCls} style={{ padding: '8px 10px' }} value={a.parent_region} onChange={(e) => set('parent_region', e.target.value)}>
                    {REGIONS.map((r) => <option key={r || 'none'} value={r}>{r || '선택 안 함'}</option>)}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-bold text-(--text-muted)">소득 구간</span>
                  <select className={selectCls} style={{ padding: '8px 10px' }} value={a.income} onChange={(e) => set('income', e.target.value)}>
                    {INCOMES.map((o) => <option key={o.v || 'none'} value={o.v}>{o.label}</option>)}
                  </select>
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-bold text-(--text-muted)">나이</span>
                  <input type="number" min="15" max="99" className={selectCls} style={{ padding: '8px 10px' }} value={a.age} onChange={(e) => set('age', e.target.value)} placeholder="예: 22" />
                </label>
              </div>

              {/* 해당 사항 토글 */}
              <p className="text-xs font-bold text-(--text-muted)" style={{ marginTop: '18px', marginBottom: '8px' }}>해당하는 항목을 켜주세요</p>
              <div className="flex flex-wrap gap-2">
                {FLAGS.map(([key, label]) => {
                  const on = a[key]
                  return (
                    <button key={key} onClick={() => set(key, !on)} className="rounded-full border transition" style={{
                      fontSize: '12px', padding: '6px 13px', fontWeight: on ? 700 : 500,
                      borderColor: on ? 'var(--brand)' : 'var(--modal-edge)',
                      background: on ? 'var(--brand)' : 'transparent',
                      color: on ? '#fff' : 'var(--text-muted)',
                    }}>
                      {on ? '✓ ' : ''}{label}
                    </button>
                  )
                })}
              </div>

              {/* 관심 유형 */}
              <p className="text-xs font-bold text-(--text-muted)" style={{ marginTop: '18px', marginBottom: '8px' }}>관심 있는 유형 <span className="font-normal text-(--text-faint)">(여러 개 · 선택 시 위로 정렬)</span></p>
              <div className="flex flex-wrap gap-2">
                {INTERESTS.map((c) => {
                  const on = a.interests.includes(c)
                  return (
                    <button key={c} onClick={() => toggleInterest(c)} className="rounded-full border transition" style={{
                      fontSize: '11.5px', padding: '5px 11px', fontWeight: on ? 700 : 500,
                      borderColor: on ? 'var(--brand)' : 'var(--modal-edge)',
                      background: on ? 'var(--brand)' : 'transparent',
                      color: on ? '#fff' : 'var(--text-muted)',
                    }}>
                      {c}
                    </button>
                  )
                })}
              </div>

              {error && <p className="text-red-400" style={{ fontSize: '12px', marginTop: '14px' }}>{error}</p>}
            </div>

            <div className="border-t border-(--border) shrink-0" style={{ padding: '12px 18px' }}>
              <button onClick={submit} disabled={loading}
                className="w-full font-bold text-white rounded-xl transition disabled:opacity-50"
                style={{ padding: '12px', background: TEAL, fontSize: '14px' }}>
                {loading ? '찾는 중…' : '맞춤 장학금 찾기'}
              </button>
            </div>
          </>
        ) : (
          <>
            <div style={{ padding: '14px 18px', overflowY: 'auto' }} className="flex-1">
              {/* 연동된 프로필 */}
              {p && (
                <div className="rounded-lg flex flex-wrap items-center gap-x-3 gap-y-1" style={{ background: 'var(--surface-2)', padding: '9px 12px', marginBottom: '14px' }}>
                  <span className="font-bold text-(--text)" style={{ fontSize: '12.5px' }}>{p.name}님</span>
                  <span className="text-(--text-muted)" style={{ fontSize: '12px' }}>학점 {p.gpa ?? '-'}</span>
                  <span className="text-(--text-muted)" style={{ fontSize: '12px' }}>{p.grade_year ? `${p.grade_year}학년` : '-'}</span>
                  <span className="text-(--text-muted)" style={{ fontSize: '12px' }}>{majorFieldLabel(p.major_field)}</span>
                  <span className="text-(--text-faint)" style={{ fontSize: '11px' }}>· 자동 연동</span>
                </div>
              )}

              {(result?.items || []).length === 0 ? (
                <p className="text-center text-(--text-faint)" style={{ fontSize: '13px', padding: '30px' }}>조건에 맞는 장학금이 없어요. 항목을 줄여 다시 시도해 보세요.</p>
              ) : (result.items).map((it) => (
                <button key={it.id} onClick={() => onPick?.(it)}
                  className="w-full text-left rounded-2xl border border-(--item-edge) hover:border-(--brand) transition"
                  style={{ padding: '13px 15px', marginBottom: '10px', background: 'var(--item-bubble)', boxShadow: 'var(--item-shadow)' }}>
                  <div className="flex items-center flex-wrap" style={{ columnGap: '8px', rowGap: '4px' }}>
                    <span className="font-semibold text-(--text)" style={{ fontSize: '13px' }}>{it.name}</span>
                    {it.category && <span className="rounded-full text-(--text-muted) bg-(--surface-2)" style={{ fontSize: '10.5px', padding: '1px 8px' }}>{it.category}</span>}
                    {it.amount && <span className="font-semibold rounded-full shrink-0" style={{ fontSize: '11px', padding: '2px 9px', background: 'var(--brand-tint2)', color: TEAL }}>{it.amount}</span>}
                    {it.expired && <span className="rounded-full font-semibold" style={{ fontSize: '10.5px', padding: '1px 8px', background: 'var(--danger-tint)', color: 'var(--danger-text)' }}>기간마감</span>}
                  </div>
                  {it.eligibility && it.eligibility !== '공고문에서 확인' && (
                    <p className="text-(--text-muted) truncate" style={{ fontSize: '12px', marginTop: '5px' }}>{it.eligibility}</p>
                  )}
                  <p className="text-(--brand)" style={{ fontSize: '11px', marginTop: '6px', fontWeight: 600 }}>자세히 보기 →</p>
                </button>
              ))}
            </div>

            <div className="border-t border-(--border) shrink-0 flex gap-2" style={{ padding: '12px 18px' }}>
              <button onClick={() => setStep('form')}
                className="font-semibold text-(--text-muted) rounded-xl border border-(--modal-edge) hover:bg-(--surface-2) transition"
                style={{ padding: '11px 16px', fontSize: '13px' }}>
                ← 다시 설문
              </button>
              <button onClick={onClose}
                className="flex-1 font-bold text-white rounded-xl transition"
                style={{ padding: '11px', background: TEAL, fontSize: '13px' }}>
                닫기
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
