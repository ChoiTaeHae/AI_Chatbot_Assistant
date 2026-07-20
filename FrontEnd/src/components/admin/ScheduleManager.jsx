import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  crawlSchedule, fetchSchedules, createSchedule, updateSchedule, deleteSchedule,
} from '../../api/admins/schedule'

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']
const DEFAULT_URL = 'https://www.wsu.ac.kr/page/haksa_list.jsp'
const ACCENT = '#005956'

function toISO(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// 이벤트 카테고리별 색 (달력 가독성 — 키워드 기반 그룹핑)
function catStyle(event) {
  const e = event || ''
  if (/수강|정정|철회|변경/.test(e)) return 'bg-blue-50 text-blue-700 border border-blue-100'
  if (/성적|평가|시험/.test(e)) return 'bg-purple-50 text-purple-700 border border-purple-100'
  if (/등록|납부|분납|장학/.test(e)) return 'bg-emerald-50 text-emerald-700 border border-emerald-100'
  if (/휴학|복학|자퇴|전과|재입학/.test(e)) return 'bg-amber-50 text-amber-700 border border-amber-100'
  if (/졸업|학위|입학/.test(e)) return 'bg-rose-50 text-rose-700 border border-rose-100'
  if (/방학|개강|종강|개학|공휴일|연휴/.test(e)) return 'bg-slate-100 text-slate-600 border border-slate-200'
  return 'bg-slate-50 text-slate-500 border border-slate-200'
}

// 해당 월을 감싸는 6주 그리드(일요일 시작) 생성 → Date[][]
function buildWeeks(year, month0) {
  const first = new Date(year, month0, 1)
  const start = new Date(first)
  start.setDate(1 - first.getDay())
  const weeks = []
  const cur = new Date(start)
  for (let w = 0; w < 6; w++) {
    const week = []
    for (let d = 0; d < 7; d++) {
      week.push(new Date(cur))
      cur.setDate(cur.getDate() + 1)
    }
    weeks.push(week)
  }
  return weeks
}

// 한 주(7일)에 걸치는 일정들을 '연속 막대' 세그먼트로 계산.
// - 기간 일정은 주 경계에서 잘려 각 주마다 하나의 막대가 된다(월~일 span).
// - 겹치는 일정은 lane(세로 층)을 달리해 쌓는다.
// - roundedLeft/Right: 실제 시작/끝이 이 주 안이면 그쪽 모서리를 둥글게(연속이면 각지게).
function computeWeekSegments(week, rows) {
  const w0 = toISO(week[0])
  const w6 = toISO(week[6])
  const evs = rows
    .filter(s => { const st = s.start_date, en = s.end_date || s.start_date; return st <= w6 && en >= w0 })
    .sort((a, b) => {
      if (a.start_date !== b.start_date) return a.start_date < b.start_date ? -1 : 1
      const al = a.end_date || a.start_date, bl = b.end_date || b.start_date
      return al < bl ? 1 : -1   // 시작 같으면 더 긴 일정 먼저(위 lane)
    })
  const lanes = []
  const segs = []
  for (const ev of evs) {
    const st = ev.start_date, en = ev.end_date || ev.start_date
    let startCol = week.findIndex(d => toISO(d) >= st)
    if (startCol < 0) startCol = 0
    let endCol = 6
    for (let i = 6; i >= 0; i--) { if (toISO(week[i]) <= en) { endCol = i; break } }
    if (endCol < startCol) endCol = startCol
    let lane = 0
    while (lanes[lane] && lanes[lane].some(s => !(endCol < s.startCol || startCol > s.endCol))) lane++
    if (!lanes[lane]) lanes[lane] = []
    lanes[lane].push({ startCol, endCol })
    segs.push({ ev, startCol, endCol, lane, roundedLeft: st >= w0, roundedRight: en <= w6 })
  }
  return { segs, maxLanes: lanes.length }
}

const EMPTY_FORM = { id: null, academic_year: '', track: '학부', event: '', start_date: '', end_date: '' }

export default function ScheduleManager() {
  const [schedules, setSchedules] = useState([])
  const [track, setTrack] = useState('학부')
  const [cursor, setCursor] = useState(() => { const t = new Date(); return new Date(t.getFullYear(), t.getMonth(), 1) })
  const [loading, setLoading] = useState(false)

  const [url, setUrl] = useState(DEFAULT_URL)
  const [crawling, setCrawling] = useState(false)
  const [crawlMsg, setCrawlMsg] = useState(null)   // {type, text}

  const [form, setForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const todayISO = toISO(new Date())

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setSchedules(await fetchSchedules())
    } catch (e) {
      setCrawlMsg({ type: 'error', text: e.message })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const trackRows = useMemo(
    () => schedules.filter(s => s.track === track && s.start_date),
    [schedules, track],
  )

  const weeks = useMemo(() => buildWeeks(cursor.getFullYear(), cursor.getMonth()), [cursor])
  const viewMonth0 = cursor.getMonth()

  // 드롭다운용 연도 목록 — 데이터에 존재하는 연도 + 현재 선택 연도
  const yearOptions = useMemo(() => {
    const ys = new Set()
    schedules.forEach(s => {
      if (s.start_date) ys.add(Number(s.start_date.slice(0, 4)))
      if (s.end_date) ys.add(Number(s.end_date.slice(0, 4)))
    })
    ys.add(cursor.getFullYear())
    return [...ys].sort((a, b) => a - b)
  }, [schedules, cursor])

  function moveMonth(delta) {
    setCursor(c => new Date(c.getFullYear(), c.getMonth() + delta, 1))
  }
  function goToday() {
    const t = new Date()
    setCursor(new Date(t.getFullYear(), t.getMonth(), 1))
  }

  async function handleCrawl() {
    if (!url.trim()) return
    setCrawling(true); setCrawlMsg(null)
    try {
      const r = await crawlSchedule(url.trim())
      setCrawlMsg({ type: 'success', text: `${r.count}건 적재 완료` })
      await load()
    } catch (e) {
      setCrawlMsg({ type: 'error', text: e.message })
    } finally {
      setCrawling(false)
    }
  }

  function openNew(prefillISO) {
    setError('')
    setForm({ ...EMPTY_FORM, track, academic_year: cursor.getFullYear(), start_date: prefillISO || '', end_date: prefillISO || '' })
  }
  function openEdit(row) {
    setError('')
    setForm({
      id: row.id,
      academic_year: row.academic_year,
      track: row.track,
      event: row.event,
      start_date: row.start_date || '',
      end_date: row.end_date || row.start_date || '',
    })
  }

  async function handleSave() {
    if (!form.event.trim() || !form.start_date) {
      setError('일정 이름과 시작일은 필수입니다.'); return
    }
    setSaving(true); setError('')
    const payload = {
      academic_year: Number(form.academic_year) || cursor.getFullYear(),
      track: form.track,
      event: form.event.trim(),
      start_date: form.start_date,
      end_date: form.end_date || form.start_date,
    }
    try {
      if (form.id) await updateSchedule(form.id, payload)
      else await createSchedule(payload)
      setForm(null)
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!form?.id) return
    if (!window.confirm('이 일정을 삭제할까요?')) return
    setSaving(true); setError('')
    try {
      await deleteSchedule(form.id)
      setForm(null)
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  const inputCls = 'border border-slate-200 text-sm outline-none focus:border-[#005956] transition'
  const inputStyle = { borderRadius: '8px', padding: '8px 10px' }

  return (
    <div className="flex flex-col" style={{ gap: '16px' }}>
      {/* ── 상단: URL 크롤 입력 (문서관리 패널과 동일 스타일) ─────── */}
      <section className="bg-white rounded-2xl shadow-sm border border-slate-100 shrink-0" style={{ padding: '20px 24px' }}>
        <div style={{ marginBottom: '14px' }}>
          <h2 className="text-base font-black text-[#05263d]">학사일정 불러오기</h2>
          <p className="text-xs text-slate-400" style={{ marginTop: '2px' }}>학사일정 페이지 URL을 크롤링해 달력에 반영합니다 · 같은 URL 재실행 시 최신 데이터로 교체</p>
        </div>
        <div className="flex items-end flex-nowrap" style={{ gap: '12px' }}>
          <div className="flex flex-col" style={{ gap: '4px', flex: 1 }}>
            <label className="text-xs font-bold text-slate-500">크롤링 URL</label>
            <input
              type="url"
              value={url}
              onChange={e => setUrl(e.target.value)}
              placeholder="https://www.wsu.ac.kr/page/haksa_list.jsp"
              className={inputCls}
              style={inputStyle}
            />
          </div>
          <button
            onClick={handleCrawl}
            disabled={crawling}
            className="flex items-center justify-center bg-[#005956] text-white text-sm font-black hover:bg-[#004a47] transition disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
            style={{ gap: '6px', borderRadius: '8px', padding: '10px 18px' }}
          >
            {crawling ? (
              <>
                <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                불러오는 중...
              </>
            ) : (
              <>
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z" />
                </svg>
                크롤링
              </>
            )}
          </button>
        </div>
        {crawlMsg && (
          <p className={`text-xs font-medium ${crawlMsg.type === 'success' ? 'text-[#005956]' : 'text-red-500'}`} style={{ marginTop: '10px' }}>
            {crawlMsg.type === 'success' && '✅ '}{crawlMsg.text}
          </p>
        )}
      </section>

      {/* ── 툴바: 트랙 / 월 이동 / 추가 ─────────────────── */}
      <div className="flex flex-wrap items-center justify-between" style={{ gap: '12px' }}>
        <div className="flex items-center bg-slate-100 rounded-lg" style={{ padding: '4px', gap: '2px' }}>
          {['학부', '대학원'].map(t => (
            <button
              key={t}
              onClick={() => setTrack(t)}
              className={`text-sm font-bold rounded-md transition ${track === t ? 'bg-white shadow-sm text-[#005956]' : 'text-slate-500 hover:text-slate-700'}`}
              style={{ padding: '6px 16px' }}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="flex items-center" style={{ gap: '8px' }}>
          <button onClick={() => moveMonth(-1)} className="flex items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 transition" style={{ width: '34px', height: '34px' }}>‹</button>
          <select
            value={cursor.getFullYear()}
            onChange={e => setCursor(new Date(Number(e.target.value), cursor.getMonth(), 1))}
            className="border border-slate-200 rounded-lg text-sm font-black text-[#05263d] bg-white outline-none focus:border-[#005956] transition cursor-pointer"
            style={{ padding: '7px 8px' }}
          >
            {yearOptions.map(y => <option key={y} value={y}>{y}년</option>)}
          </select>
          <select
            value={cursor.getMonth()}
            onChange={e => setCursor(new Date(cursor.getFullYear(), Number(e.target.value), 1))}
            className="border border-slate-200 rounded-lg text-sm font-black text-[#05263d] bg-white outline-none focus:border-[#005956] transition cursor-pointer"
            style={{ padding: '7px 8px' }}
          >
            {Array.from({ length: 12 }, (_, i) => i).map(m => <option key={m} value={m}>{m + 1}월</option>)}
          </select>
          <button onClick={() => moveMonth(1)} className="flex items-center justify-center rounded-lg border border-slate-200 text-slate-500 hover:bg-slate-50 transition" style={{ width: '34px', height: '34px' }}>›</button>
          <button onClick={goToday} className="rounded-lg border border-slate-200 text-sm font-bold text-slate-500 hover:bg-slate-50 transition" style={{ padding: '7px 14px', marginLeft: '4px' }}>오늘</button>
        </div>

        <button
          onClick={() => openNew('')}
          className="flex items-center bg-[#005956] text-white text-sm font-black hover:bg-[#004a47] transition"
          style={{ gap: '6px', borderRadius: '8px', padding: '9px 16px' }}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          일정 추가
        </button>
      </div>

      {/* ── 달력 그리드 ─────────────────────────────────── */}
      <div className="bg-white rounded-2xl shadow-sm border border-slate-100 overflow-hidden">
        <div className="grid grid-cols-7 border-b border-slate-100 bg-slate-50/50">
          {WEEKDAYS.map((w, i) => (
            <div key={w} className={`text-center text-xs font-bold ${i === 0 ? 'text-red-400' : i === 6 ? 'text-blue-400' : 'text-slate-400'}`} style={{ padding: '10px 0' }}>{w}</div>
          ))}
        </div>
        <div>
          {weeks.map((week, wi) => {
            const { segs, maxLanes } = computeWeekSegments(week, trackRows)
            const BARS_TOP = 28      // 날짜 숫자 영역 높이
            const LANE_H = 26        // 막대(22) + 세로 간격(4)
            const cellH = Math.max(118, BARS_TOP + maxLanes * LANE_H + 8)
            return (
              <div key={wi} className={`relative ${wi < weeks.length - 1 ? 'border-b border-slate-100' : ''}`}>
                {/* 배경 셀: 테두리 · 날짜 숫자 · 더블클릭 추가 */}
                <div className="grid grid-cols-7">
                  {week.map((day, ci) => {
                    const inMonth = day.getMonth() === viewMonth0
                    const isToday = toISO(day) === todayISO
                    return (
                      <div
                        key={ci}
                        className={`${ci !== 6 ? 'border-r border-slate-100' : ''} ${inMonth ? 'bg-white hover:bg-slate-50/40' : 'bg-slate-50/40'} transition`}
                        style={{ minHeight: `${cellH}px`, padding: '8px' }}
                        onDoubleClick={() => inMonth && openNew(toISO(day))}
                      >
                        <span className={`text-xs font-bold ${!inMonth ? 'text-slate-300' : day.getDay() === 0 ? 'text-red-400' : day.getDay() === 6 ? 'text-blue-400' : 'text-slate-500'}`}>
                          {isToday
                            ? <span className="inline-flex items-center justify-center rounded-full bg-[#005956] text-white" style={{ width: '22px', height: '22px' }}>{day.getDate()}</span>
                            : day.getDate()}
                        </span>
                      </div>
                    )
                  })}
                </div>
                {/* 이벤트 막대 오버레이 (기간 일정을 하나의 연속 막대로) */}
                <div className="grid grid-cols-7" style={{ position: 'absolute', left: 0, right: 0, top: `${BARS_TOP}px`, gridAutoRows: `${LANE_H}px`, pointerEvents: 'none' }}>
                  {segs.map((seg, si) => (
                    <button
                      key={si}
                      onClick={() => openEdit(seg.ev)}
                      title={`${seg.ev.event} (${seg.ev.start_date}${seg.ev.end_date && seg.ev.end_date !== seg.ev.start_date ? ' ~ ' + seg.ev.end_date : ''})`}
                      className={`flex items-center text-[11px] font-medium hover:brightness-95 transition ${catStyle(seg.ev.event)}`}
                      style={{
                        gridColumn: `${seg.startCol + 1} / ${seg.endCol + 2}`,
                        gridRow: seg.lane + 1,
                        pointerEvents: 'auto',
                        height: '22px',
                        padding: '0 6px',
                        overflow: 'hidden',
                        marginLeft: seg.roundedLeft ? '3px' : '0',
                        marginRight: seg.roundedRight ? '3px' : '0',
                        borderTopLeftRadius: seg.roundedLeft ? '4px' : '0',
                        borderBottomLeftRadius: seg.roundedLeft ? '4px' : '0',
                        borderTopRightRadius: seg.roundedRight ? '4px' : '0',
                        borderBottomRightRadius: seg.roundedRight ? '4px' : '0',
                      }}
                    >
                      <span className="truncate">{seg.ev.event}</span>
                    </button>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </div>
      <p className="text-xs text-slate-400">일정을 클릭하면 수정·삭제, 빈 날짜를 더블클릭하면 그 날짜로 추가할 수 있어요.{loading && ' · 불러오는 중…'}</p>

      {/* ── 추가/수정 모달 ─────────────────────────────── */}
      {form && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" style={{ padding: '16px' }} onClick={() => !saving && setForm(null)}>
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md" style={{ padding: '24px' }} onClick={e => e.stopPropagation()}>
            <h3 className="text-base font-black text-[#05263d]" style={{ marginBottom: '18px' }}>{form.id ? '일정 수정' : '일정 추가'}</h3>
            <div className="flex flex-col" style={{ gap: '14px' }}>
              <div className="flex flex-col" style={{ gap: '4px' }}>
                <label className="text-xs font-bold text-slate-500">일정 이름</label>
                <input value={form.event} onChange={e => setForm({ ...form, event: e.target.value })}
                  className={inputCls} style={inputStyle} placeholder="예: 2학기 수강신청 기간" />
              </div>
              <div className="flex" style={{ gap: '12px' }}>
                <div className="flex flex-col" style={{ gap: '4px', flex: 1 }}>
                  <label className="text-xs font-bold text-slate-500">시작일</label>
                  <input type="date" value={form.start_date} onChange={e => setForm({ ...form, start_date: e.target.value })} className={inputCls} style={inputStyle} />
                </div>
                <div className="flex flex-col" style={{ gap: '4px', flex: 1 }}>
                  <label className="text-xs font-bold text-slate-500">종료일 <span className="text-slate-300 font-medium">(하루면 비움)</span></label>
                  <input type="date" value={form.end_date} onChange={e => setForm({ ...form, end_date: e.target.value })} className={inputCls} style={inputStyle} />
                </div>
              </div>
              <div className="flex" style={{ gap: '12px' }}>
                <div className="flex flex-col" style={{ gap: '4px', flex: 1 }}>
                  <label className="text-xs font-bold text-slate-500">트랙</label>
                  <select value={form.track} onChange={e => setForm({ ...form, track: e.target.value })} className={`${inputCls} bg-white`} style={inputStyle}>
                    <option value="학부">학부</option>
                    <option value="대학원">대학원</option>
                  </select>
                </div>
                <div className="flex flex-col" style={{ gap: '4px', flex: 1 }}>
                  <label className="text-xs font-bold text-slate-500">학년도</label>
                  <input type="number" value={form.academic_year} onChange={e => setForm({ ...form, academic_year: e.target.value })} className={inputCls} style={inputStyle} placeholder="2026" />
                </div>
              </div>
              {error && <p className="text-xs font-medium text-red-500">{error}</p>}
            </div>
            <div className="flex items-center justify-between" style={{ marginTop: '22px' }}>
              {form.id
                ? <button onClick={handleDelete} disabled={saving} className="text-sm font-bold text-red-500 hover:bg-red-50 rounded-lg transition disabled:opacity-50" style={{ padding: '9px 12px' }}>삭제</button>
                : <span />}
              <div className="flex" style={{ gap: '8px' }}>
                <button onClick={() => setForm(null)} disabled={saving} className="border border-slate-200 text-sm font-bold text-slate-500 hover:bg-slate-50 rounded-lg transition" style={{ padding: '9px 16px' }}>취소</button>
                <button onClick={handleSave} disabled={saving} className="bg-[#005956] text-white text-sm font-black hover:bg-[#004a47] rounded-lg transition disabled:opacity-50" style={{ padding: '9px 18px' }}>{saving ? '저장 중…' : '저장'}</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
