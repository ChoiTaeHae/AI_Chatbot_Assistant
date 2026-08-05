import { useState, useMemo } from 'react'
import useIsMobile from '../../hooks/useIsMobile'
// 달력 공통 로직은 scheduleUtils에 모아 ScheduleWidget(사이드바)과 공유한다.
import { WD, toISO, fmtDate, catStyle, buildMonthWeeks, segsForWeek } from './scheduleUtils'

// 카드 정적 라벨 다국어 (일정명 등 동적 데이터는 백엔드 값 그대로).
const SC = {
  ko: { title: '학사일정', ended: '종료', prev: '이전 일정', next: '다음 일정',
        cal: '달력', list: '목록', today: '오늘', count: '건' },
  en: { title: 'Academic Calendar', ended: 'Ended', prev: 'Previous', next: 'Next',
        cal: 'Calendar', list: 'List', today: 'Today', count: '' },
  zh: { title: '学事日程', ended: '已结束', prev: '上一个', next: '下一个',
        cal: '日历', list: '列表', today: '今天', count: '项' },
}

// 목록 뷰용 날짜 축약 — 같은 달이면 '12~14일', 달을 넘기면 '11/30~12/4'.
// 달력 뷰의 fmtDate와 달리 한 줄에 여러 건이 쌓이므로 짧게 쓴다.
function shortRange(s, e) {
  const [sy, sm, sd] = s.split('-').map(Number)
  const [ey, em, ed] = (e || s).split('-').map(Number)
  if (s === (e || s)) return `${sd}일`
  if (sy === ey && sm === em) return `${sd}~${ed}일`
  return `${sm}/${sd}~${em}/${ed}`
}

export default function ScheduleCard({ card, lang = 'ko' }) {
  const isMobile = useIsMobile()
  const sc = SC[lang] || SC.ko
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
  // 달력은 한 달씩만 보여 전체를 훑기 어렵다. 같은 데이터를 월별 목록으로도 볼 수 있게 한다.
  // ('학사일정 전체 알려줘'는 카드에 현재 학년도 전부가 실려 온다)
  const [view, setView] = useState('calendar')

  // 목록 뷰용 월별 묶음 — [{ key, label, items: [...] }]
  const months = useMemo(() => {
    const out = []
    for (const e of events) {
      const y = e.start_date.slice(0, 4), m = Number(e.start_date.slice(5, 7))
      const key = `${y}-${m}`
      const last = out[out.length - 1]
      if (last && last.key === key) last.items.push(e)
      else out.push({ key, label: `${y}년 ${m}월`, items: [e] })
    }
    return out
  }, [events])

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
      <div className="grid grid-cols-7 border-b border-(--border)">
        {WD.map((w, k) => (
          <div key={w} className={`text-center ${k === 0 ? 'text-red-400' : k === 6 ? 'text-blue-400' : 'text-(--text-faint)'}`} style={{ fontSize: isMobile ? '10px' : '11px', fontWeight: 700, padding: isMobile ? '4px 0' : '5px 0' }}>{w}</div>
        ))}
      </div>
      {/* 월 달력 그리드 */}
      {weeks.map((week, wi) => {
        const { segs, maxLanes } = segsForWeek(week, events)
        const BARS_TOP = 26, LANE_H = 19
        const cellH = Math.max(52, BARS_TOP + maxLanes * LANE_H + 5)
        return (
          <div key={wi} className={wi < weeks.length - 1 ? 'border-b border-(--border)' : ''}>
            <div className="relative">
              <div className="grid grid-cols-7">
                {week.map((day, ci) => {
                  const inMonth = day.getMonth() === fm
                  const isToday = toISO(day) === todayISO
                  return (
                    <div key={ci} className={`${ci !== 6 ? 'border-r border-(--border)' : ''} ${inMonth ? '' : 'bg-(--surface-2)/40'}`} style={{ minHeight: `${cellH}px`, padding: isMobile ? '3px 2px' : '4px 5px' }}>
                      <span className={`${!inMonth ? 'text-(--text-faint)' : isToday ? '' : day.getDay() === 0 ? 'text-red-400' : day.getDay() === 6 ? 'text-blue-400' : 'text-(--text-muted)'}`} style={{ fontSize: '11px', fontWeight: 700, position: 'relative', zIndex: 1 }}>
                        {isToday
                          ? <span className="inline-flex items-center justify-center rounded-full bg-(--brand) text-white" style={{ width: isMobile ? '16px' : '18px', height: isMobile ? '16px' : '18px', fontSize: '10px' }}>{day.getDate()}</span>
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
                        padding: isMobile ? '0 3px' : '0 5px',
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

  // 월별 목록 뷰 — 달력이 한 달씩만 보여주는 한계를 보완(전체 일정을 한 번에 훑기).
  const list = (
    <div style={{ maxHeight: '340px', overflowY: 'auto' }}>
      {months.map(mo => (
        <div key={mo.key}>
          <div className="sticky top-0 flex items-baseline gap-2 bg-(--surface-2) border-b border-(--border)"
               style={{ padding: '5px 12px' }}>
            <span className="text-xs font-black text-(--text)">{mo.label}</span>
            <span className="text-[10px] text-(--text-faint)">{mo.items.length}{sc.count}</span>
          </div>
          {mo.items.map((e, k) => {
            const past = !!todayISO && e.end_date < todayISO
            const now = !!todayISO && e.start_date <= todayISO && e.end_date >= todayISO
            return (
              <div key={`${e.start_date}|${e.event}|${k}`}
                   className="flex items-baseline border-b border-(--border)"
                   style={{ padding: '6px 12px', gap: '10px' }}>
                <span className={`shrink-0 text-[11px] font-bold tabular-nums ${past ? 'text-(--text-faint)' : 'text-(--brand)'}`}
                      style={{ width: '62px' }}>{shortRange(e.start_date, e.end_date)}</span>
                <span className={`flex-1 min-w-0 text-xs ${past ? 'text-(--text-faint) line-through' : 'text-(--text-body)'}`}>{e.event}</span>
                {now && <span className="shrink-0 text-[10px] font-bold text-(--brand) bg-(--brand-tint) rounded"
                              style={{ padding: '1px 6px' }}>{sc.today}</span>}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )

  const toggle = (
    <div className="flex rounded-md overflow-hidden border border-(--brand-a20)">
      {[['calendar', sc.cal], ['list', sc.list]].map(([v, label]) => (
        <button key={v} onClick={() => setView(v)} aria-pressed={view === v}
          className={`text-[11px] font-bold transition ${view === v
            ? 'bg-(--brand) text-white'
            : 'text-(--text-muted) hover:text-(--text-body)'}`}
          style={{ padding: '3px 9px' }}>{label}</button>
      ))}
    </div>
  )

  return (
    <div className="flex items-center" style={{ marginTop: '14px', gap: '2px' }}>
      {/* 왼쪽 화살표 — 달력 뷰에서만(목록은 스크롤로 이동) */}
      {multi && view === 'calendar' && (
        <button onClick={() => setIdx(v => Math.max(0, v - 1))} disabled={i === 0}
          className="shrink-0 flex items-center justify-center rounded-full bg-(--surface-card) border border-(--border) text-(--text-muted) shadow-sm hover:bg-(--surface-2) hover:text-(--text-body) disabled:opacity-30 disabled:hover:bg-(--surface-card) transition"
          style={{ width: '28px', height: '28px' }} aria-label={sc.prev}>
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
          </svg>
        </button>
      )}

      {/* 달력 카드 */}
      <div className="flex-1 min-w-0 rounded-xl border border-(--brand-a20) overflow-hidden bg-(--surface-card)">
        {/* 헤더: 제목 + 월 */}
        <div className="flex items-center justify-between bg-(--brand-tint)" style={{ padding: '9px 12px' }}>
          <div className="flex items-center gap-1.5">
            <svg className="h-4 w-4 text-(--brand)" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0V11.25A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
            </svg>
            <span className="text-sm font-bold text-(--brand)">{sc.title}</span>
          </div>
          <div className="flex items-center" style={{ gap: '8px' }}>
            {view === 'calendar'
              ? <span className="text-sm font-black text-(--text)">{fy}년 {fm + 1}월{multi && <span className="text-[11px] font-medium text-(--text-faint)" style={{ marginLeft: '6px' }}>{i + 1}/{events.length}</span>}</span>
              : <span className="text-[11px] font-medium text-(--text-faint)">{events.length}{sc.count}</span>}
            {multi && toggle}
          </div>
        </div>

        {view === 'calendar' ? (
          <>
            {/* 포커스 일정 — 이름 + 기간 강조, 지난 일정이면 '종료' 표시 */}
            <div className="border-b border-(--border) flex items-baseline flex-wrap" style={{ padding: '7px 12px', gap: '6px' }}>
              <span className={`text-sm font-black ${focalPast ? 'text-(--text-faint) line-through' : 'text-(--text)'}`}>{focal.event}</span>
              <span className={`text-xs font-bold ${focalPast ? 'text-(--text-faint)' : 'text-(--brand)'}`}>{focalRange}</span>
              {focalPast && <span className="text-[10px] font-bold text-(--text-muted) bg-(--surface-2) rounded" style={{ padding: '1px 6px' }}>{sc.ended}</span>}
            </div>
            {grid}
          </>
        ) : list}
      </div>

      {/* 오른쪽 화살표 — 달력 뷰에서만 */}
      {multi && view === 'calendar' && (
        <button onClick={() => setIdx(v => Math.min(events.length - 1, v + 1))} disabled={i === events.length - 1}
          className="shrink-0 flex items-center justify-center rounded-full bg-(--surface-card) border border-(--border) text-(--text-muted) shadow-sm hover:bg-(--surface-2) hover:text-(--text-body) disabled:opacity-30 disabled:hover:bg-(--surface-card) transition"
          style={{ width: '28px', height: '28px' }} aria-label={sc.next}>
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
        </button>
      )}
    </div>
  )
}
