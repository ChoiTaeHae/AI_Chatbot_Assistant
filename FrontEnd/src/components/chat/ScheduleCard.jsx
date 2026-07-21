import { useState, useMemo } from 'react'

const WD = ['일', '월', '화', '수', '목', '금', '토']

function toISO(d) {
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), da = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${da}`
}
function fmtDate(s) { return `${Number(s.slice(5, 7))}월 ${Number(s.slice(8, 10))}일` }

// 카테고리별 색 (관리자 달력과 동일 팔레트)
function catStyle(e) {
  if (/수강|정정|철회|변경/.test(e)) return 'bg-blue-100 text-blue-700'
  if (/성적|평가|시험/.test(e)) return 'bg-purple-100 text-purple-700'
  if (/등록|납부|분납|장학/.test(e)) return 'bg-emerald-100 text-emerald-700'
  if (/휴학|복학|자퇴|전과|재입학/.test(e)) return 'bg-amber-100 text-amber-700'
  if (/졸업|학위|입학/.test(e)) return 'bg-rose-100 text-rose-700'
  if (/방학|개강|종강|개학|공휴일|연휴/.test(e)) return 'bg-slate-200 text-slate-700'
  return 'bg-slate-100 text-slate-600'
}

// 한 달을 감싸는 주 배열(일요일 시작). 항상 6줄 고정 → 달마다 카드 높이가 일정해져
// 페이지를 넘겨도(화살표) 세로 중앙의 버튼 위치가 안 바뀐다.
function buildMonthWeeks(year, month0) {
  const first = new Date(year, month0, 1)
  const cur = new Date(first); cur.setDate(1 - first.getDay())
  const weeks = []
  for (let w = 0; w < 6; w++) {
    const week = []
    for (let i = 0; i < 7; i++) { week.push(new Date(cur)); cur.setDate(cur.getDate() + 1) }
    weeks.push(week)
  }
  return weeks
}

// 한 주에 걸치는 일정 → 연속 막대 세그먼트 + lane
function segsForWeek(days, events) {
  const w0 = toISO(days[0]), w6 = toISO(days[6])
  const evs = events
    .filter(e => { const st = e.start_date, en = e.end_date || e.start_date; return st <= w6 && en >= w0 })
    .sort((a, b) => (a.start_date < b.start_date ? -1 : a.start_date > b.start_date ? 1 : 0))
  const lanes = [], segs = []
  for (const ev of evs) {
    const st = ev.start_date, en = ev.end_date || ev.start_date
    let startCol = days.findIndex(d => toISO(d) >= st); if (startCol < 0) startCol = 0
    let endCol = 6; for (let i = 6; i >= 0; i--) { if (toISO(days[i]) <= en) { endCol = i; break } }
    if (endCol < startCol) endCol = startCol
    let lane = 0
    while (lanes[lane] && lanes[lane].some(s => !(endCol < s.startCol || startCol > s.endCol))) lane++
    if (!lanes[lane]) lanes[lane] = []
    lanes[lane].push({ startCol, endCol })
    segs.push({ ev, startCol, endCol, lane, roundedLeft: st >= w0, roundedRight: en <= w6 })
  }
  return { segs, maxLanes: lanes.length }
}

export default function ScheduleCard({ card }) {
  const todayISO = card?.today
  const events = useMemo(() => (card?.events || [])
    .filter(e => e.start_date)
    .map(e => ({ event: e.event, start_date: e.start_date, end_date: e.end_date || e.start_date }))
    .sort((a, b) => (a.start_date < b.start_date ? -1 : a.start_date > b.start_date ? 1 : 0)),
    [card])

  // 초기 페이지 = 가장 가까운 다가오는 일정(2학기처럼) — 없으면 마지막(최근 과거)
  const initialIdx = useMemo(() => {
    const i = events.findIndex(e => !todayISO || e.end_date >= todayISO)
    return i >= 0 ? i : Math.max(0, events.length - 1)
  }, [events, todayISO])

  const [idx, setIdx] = useState(initialIdx)
  if (!events.length) return null

  const i = Math.min(idx, events.length - 1)
  const focal = events[i]
  const focalKey = `${focal.start_date}|${focal.event}`
  const fy = Number(focal.start_date.slice(0, 4)), fm = Number(focal.start_date.slice(5, 7)) - 1
  const weeks = buildMonthWeeks(fy, fm)
  const focalRange = focal.end_date && focal.end_date !== focal.start_date
    ? `${fmtDate(focal.start_date)} ~ ${fmtDate(focal.end_date)}`
    : fmtDate(focal.start_date)
  const multi = events.length > 1
  const focalPast = !!todayISO && focal.end_date < todayISO

  const grid = (
    <div className="flex-1 min-w-0">
      {/* 요일 헤더 */}
      <div className="grid grid-cols-7 border-b border-slate-100">
        {WD.map((w, k) => (
          <div key={w} className={`text-center ${k === 0 ? 'text-red-400' : k === 6 ? 'text-blue-400' : 'text-slate-400'}`} style={{ fontSize: '11px', fontWeight: 700, padding: '5px 0' }}>{w}</div>
        ))}
      </div>
      {/* 월 달력 그리드 */}
      {weeks.map((week, wi) => {
        const { segs, maxLanes } = segsForWeek(week, events)
        const BARS_TOP = 26, LANE_H = 19
        const cellH = Math.max(52, BARS_TOP + maxLanes * LANE_H + 5)
        return (
          <div key={wi} className={wi < weeks.length - 1 ? 'border-b border-slate-50' : ''}>
            <div className="relative">
              <div className="grid grid-cols-7">
                {week.map((day, ci) => {
                  const inMonth = day.getMonth() === fm
                  const isToday = toISO(day) === todayISO
                  return (
                    <div key={ci} className={`${ci !== 6 ? 'border-r border-slate-50' : ''} ${inMonth ? '' : 'bg-slate-50/40'}`} style={{ minHeight: `${cellH}px`, padding: '4px 5px' }}>
                      <span className={`${!inMonth ? 'text-slate-300' : isToday ? '' : day.getDay() === 0 ? 'text-red-400' : day.getDay() === 6 ? 'text-blue-400' : 'text-slate-600'}`} style={{ fontSize: '11px', fontWeight: 700, position: 'relative', zIndex: 1 }}>
                        {isToday
                          ? <span className="inline-flex items-center justify-center rounded-full bg-[#005956] text-white" style={{ width: '18px', height: '18px', fontSize: '10px' }}>{day.getDate()}</span>
                          : day.getDate()}
                      </span>
                    </div>
                  )
                })}
              </div>
              {/* 막대 오버레이 (포커스 일정은 굵게·선명, 나머지는 흐리게) */}
              <div className="grid grid-cols-7" style={{ position: 'absolute', left: 0, right: 0, top: `${BARS_TOP}px`, gridAutoRows: `${LANE_H}px`, pointerEvents: 'none' }}>
                {segs.map((seg, si) => {
                  const isFocal = `${seg.ev.start_date}|${seg.ev.event}` === focalKey
                  const segPast = !!todayISO && (seg.ev.end_date || seg.ev.start_date) < todayISO
                  return (
                    <div
                      key={si}
                      title={`${seg.ev.event} (${seg.ev.start_date}${seg.ev.end_date && seg.ev.end_date !== seg.ev.start_date ? ' ~ ' + seg.ev.end_date : ''})`}
                      className={`flex items-center ${catStyle(seg.ev.event)}`}
                      style={{
                        gridColumn: `${seg.startCol + 1} / ${seg.endCol + 2}`,
                        gridRow: seg.lane + 1,
                        height: '16px',
                        padding: '0 5px',
                        overflow: 'hidden',
                        opacity: isFocal ? 1 : 0.45,
                        marginLeft: seg.roundedLeft ? '2px' : '0',
                        marginRight: seg.roundedRight ? '2px' : '0',
                        borderTopLeftRadius: seg.roundedLeft ? '3px' : '0',
                        borderBottomLeftRadius: seg.roundedLeft ? '3px' : '0',
                        borderTopRightRadius: seg.roundedRight ? '3px' : '0',
                        borderBottomRightRadius: seg.roundedRight ? '3px' : '0',
                      }}
                    >
                      <span className="truncate" style={{ fontSize: '10px', fontWeight: isFocal ? 800 : 500, lineHeight: 1, textDecoration: segPast ? 'line-through' : 'none' }}>{seg.ev.event}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )

  return (
    <div className="flex items-center" style={{ marginTop: '14px', gap: '2px' }}>
      {/* 왼쪽 화살표 — 카드 바깥, 흰 배경 + 회색 테두리 원형 버튼 */}
      {multi && (
        <button onClick={() => setIdx(v => Math.max(0, v - 1))} disabled={i === 0}
          className="shrink-0 flex items-center justify-center rounded-full bg-white border border-slate-200 text-slate-500 shadow-sm hover:bg-slate-50 hover:text-slate-700 disabled:opacity-30 disabled:hover:bg-white transition"
          style={{ width: '28px', height: '28px' }} aria-label="이전 일정">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
        </button>
      )}

      {/* 달력 카드 */}
      <div className="flex-1 min-w-0 rounded-xl border border-[#005956]/20 overflow-hidden bg-white">
        {/* 헤더: 제목 + 월 */}
        <div className="flex items-center justify-between bg-[#f0f9f8]" style={{ padding: '9px 12px' }}>
          <div className="flex items-center gap-1.5">
            <svg className="h-4 w-4 text-[#005956]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0V11.25A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
            </svg>
            <span className="text-sm font-bold text-[#005956]">학사일정</span>
          </div>
          <span className="text-sm font-black text-[#05263d]">{fy}년 {fm + 1}월{multi && <span className="text-[11px] font-medium text-slate-300" style={{ marginLeft: '6px' }}>{i + 1}/{events.length}</span>}</span>
        </div>

        {/* 포커스 일정 — 이름 + 기간 강조, 지난 일정이면 '종료' 표시 */}
        <div className="border-b border-slate-100 flex items-baseline flex-wrap" style={{ padding: '7px 12px', gap: '6px' }}>
          <span className={`text-sm font-black ${focalPast ? 'text-slate-400 line-through' : 'text-[#05263d]'}`}>{focal.event}</span>
          <span className={`text-xs font-bold ${focalPast ? 'text-slate-300' : 'text-[#005956]'}`}>{focalRange}</span>
          {focalPast && <span className="text-[10px] font-bold text-slate-500 bg-slate-100 rounded" style={{ padding: '1px 6px' }}>종료</span>}
        </div>

        {grid}
      </div>

      {/* 오른쪽 화살표 — 카드 바깥, 흰 배경 + 회색 테두리 원형 버튼 */}
      {multi && (
        <button onClick={() => setIdx(v => Math.min(events.length - 1, v + 1))} disabled={i === events.length - 1}
          className="shrink-0 flex items-center justify-center rounded-full bg-white border border-slate-200 text-slate-500 shadow-sm hover:bg-slate-50 hover:text-slate-700 disabled:opacity-30 disabled:hover:bg-white transition"
          style={{ width: '28px', height: '28px' }} aria-label="다음 일정">
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
        </button>
      )}
    </div>
  )
}
