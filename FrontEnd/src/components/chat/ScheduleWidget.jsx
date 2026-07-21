import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { fetchScheduleMonth, fetchScheduleUpcoming } from '../../api/schedule'

const WD = ['일', '월', '화', '수', '목', '금', '토']
// 주 한 줄 높이(px) — 팝업을 absolute로 띄울 때 top 계산에 쓰므로 고정값이어야 한다.
const ROW_H = 30

const T = {
  ko: { title: '학사일정', upcoming: '다가오는 일정', none: '등록된 학사일정이 없어요' },
  en: { title: 'Academic Calendar', upcoming: 'Upcoming', none: 'No academic schedule' },
  zh: { title: '学事日程', upcoming: '即将到来', none: '暂无学事日程' },
}

function toISO(d) {
  const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), da = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${da}`
}
function fmtMD(iso) { return `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}` }
function fmtRange(s, e) {
  if (!s) return ''
  return (e && e !== s) ? `${fmtMD(s)} ~ ${fmtMD(e)}` : fmtMD(s)
}

// 해당 월을 감싸는 주 배열(일요일 시작) — 필요한 주만
function buildWeeks(year, month0) {
  const first = new Date(year, month0, 1)
  const lastDay = new Date(year, month0 + 1, 0)
  const cur = new Date(first); cur.setDate(1 - first.getDay())
  const weeks = []
  for (let w = 0; w < 6; w++) {
    const week = []
    for (let i = 0; i < 7; i++) { week.push(new Date(cur)); cur.setDate(cur.getDate() + 1) }
    weeks.push(week)
    if (cur > lastDay) break
  }
  return weeks
}

export default function ScheduleWidget({ lang = 'ko' }) {
  const t = T[lang] || T.ko
  const [cursor, setCursor] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1) })
  const [events, setEvents] = useState([])
  const [upcoming, setUpcoming] = useState([])
  const [todayISO, setTodayISO] = useState(toISO(new Date()))
  const [sel, setSel] = useState(null)   // { iso, weekIdx, colIdx }
  const calRef = useRef(null)

  // 달력 바깥을 클릭하면 상세 팝업 닫기
  // (팝업을 연 클릭 자체는 달력 안에서 발생하므로 contains 검사에 걸려 즉시 닫히지 않는다)
  useEffect(() => {
    if (!sel) return
    function onDocClick(e) {
      if (calRef.current && !calRef.current.contains(e.target)) setSel(null)
    }
    document.addEventListener('click', onDocClick)
    return () => document.removeEventListener('click', onDocClick)
  }, [sel])

  // 다가오는 일정 — 항상 고정 표시 (월 이동과 무관)
  useEffect(() => {
    fetchScheduleUpcoming(3)
      .then(d => { setUpcoming(d.events || []); if (d.today) setTodayISO(d.today) })
      .catch(() => setUpcoming([]))
  }, [])

  // 월별 일정 — 달력 점 표시용
  useEffect(() => {
    let alive = true
    setSel(null)   // 월 이동 시 팝업 닫기
    fetchScheduleMonth(cursor.getFullYear(), cursor.getMonth() + 1)
      .then(d => { if (alive) setEvents(d.events || []) })
      .catch(() => { if (alive) setEvents([]) })
    return () => { alive = false }
  }, [cursor])

  const weeks = useMemo(() => buildWeeks(cursor.getFullYear(), cursor.getMonth()), [cursor])

  // 날짜(ISO) → 그날 걸치는 일정들
  const eventsOn = useCallback((iso) => events.filter(e => {
    const st = e.start_date, en = e.end_date || e.start_date
    return st && st <= iso && iso <= en
  }), [events])

  const selEvents = sel ? eventsOn(sel.iso) : []

  return (
    <section className="border border-slate-200 rounded-xl bg-white shrink-0 overflow-hidden" style={{ marginTop: '14px' }}>
      <div style={{ padding: '12px' }}>
        {/* 헤더: 제목 + 월 이동 */}
        <div className="flex items-center justify-between" style={{ marginBottom: '8px' }}>
          <span className="text-xs font-bold text-slate-800">📅 {t.title}</span>
          <div className="flex items-center" style={{ gap: '2px' }}>
            <button onClick={() => setCursor(c => new Date(c.getFullYear(), c.getMonth() - 1, 1))}
              className="rounded text-slate-400 hover:text-[#005956] hover:bg-slate-50 transition"
              style={{ width: '18px', height: '18px', fontSize: '13px', lineHeight: 1 }} aria-label="이전 달">‹</button>
            <span className="text-slate-600 text-center" style={{ fontSize: '11px', fontWeight: 700, minWidth: '56px' }}>
              {cursor.getFullYear()}.{String(cursor.getMonth() + 1).padStart(2, '0')}
            </span>
            <button onClick={() => setCursor(c => new Date(c.getFullYear(), c.getMonth() + 1, 1))}
              className="rounded text-slate-400 hover:text-[#005956] hover:bg-slate-50 transition"
              style={{ width: '18px', height: '18px', fontSize: '13px', lineHeight: 1 }} aria-label="다음 달">›</button>
          </div>
        </div>

        {/* 요일 */}
        <div className="grid grid-cols-7">
          {WD.map((w, i) => (
            <div key={w} className={`text-center ${i === 0 ? 'text-red-300' : i === 6 ? 'text-blue-300' : 'text-slate-300'}`}
              style={{ fontSize: '10px', fontWeight: 700, paddingBottom: '3px' }}>{w}</div>
          ))}
        </div>

        {/* 달력 — 상세 팝업은 absolute로 달력 '위에 덮이게' 해서 아래 내용이 밀리지 않는다.
            좁은 폭(264px)이라 팝업은 컨테이너 전체 너비를 쓰고, 삼각으로 해당 요일을 가리킨다. */}
        <div className="relative" ref={calRef}>
          {weeks.map((week, wi) => (
            <div key={wi} className="grid grid-cols-7" style={{ height: `${ROW_H}px` }}>
              {week.map((day, ci) => {
                const iso = toISO(day)
                const inMonth = day.getMonth() === cursor.getMonth()
                const isToday = iso === todayISO
                const has = inMonth && eventsOn(iso).length > 0
                const isSel = sel?.iso === iso
                return (
                  // disabled 대신 onClick 가드 — disabled 버튼은 커서가 not-allowed(🚫)로 바뀐다
                  <div
                    key={ci}
                    onClick={() => setSel(
                      has && !isSel ? { iso, weekIdx: wi, colIdx: ci } : null   // 빈 날짜/같은 날짜 → 닫기
                    )}
                    className={`flex flex-col items-center justify-start rounded ${has ? 'cursor-pointer hover:bg-slate-50' : ''}`}
                    style={{ paddingTop: '3px' }}
                  >
                    <span
                      className={`inline-flex items-center justify-center rounded-full ${
                        isToday ? 'bg-[#005956] text-white'
                        : isSel ? 'bg-[#005956]/10 text-[#005956]'
                        : !inMonth ? 'text-slate-200'
                        : day.getDay() === 0 ? 'text-red-400' : day.getDay() === 6 ? 'text-blue-400' : 'text-slate-600'
                      }`}
                      style={{ width: '18px', height: '18px', fontSize: '10px', fontWeight: 700 }}
                    >
                      {day.getDate()}
                    </span>
                    {/* 일정 있는 날 표시 */}
                    <span
                      className={`rounded-full ${has ? (isSel ? 'bg-[#005956]' : 'bg-[#005956]/45') : 'bg-transparent'}`}
                      style={{ width: '4px', height: '4px', marginTop: '2px' }}
                    />
                  </div>
                )
              })}
            </div>
          ))}

          {/* 선택한 날짜 상세 — 클릭한 주 아래에 겹쳐서 표시 (달력을 밀지 않음) */}
          {sel && (
            <div style={{ position: 'absolute', top: `${(sel.weekIdx + 1) * ROW_H}px`, left: 0, right: 0, zIndex: 20 }}>
              {/* 해당 요일을 가리키는 삼각 */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)' }}>
                <div style={{ gridColumn: sel.colIdx + 1, display: 'flex', justifyContent: 'center' }}>
                  <span style={{
                    width: 0, height: 0,
                    borderLeft: '5px solid transparent', borderRight: '5px solid transparent',
                    borderBottom: '5px solid #ffffff',
                    filter: 'drop-shadow(0 -1px 0 rgba(0,89,86,0.3))',
                  }} />
                </div>
              </div>
              <div className="rounded-lg bg-white border border-[#005956]/30 shadow-lg" style={{ padding: '7px 9px' }}>
                <div className="flex items-center justify-between" style={{ marginBottom: '4px' }}>
                  <p className="font-bold text-[#005956]" style={{ fontSize: '11px' }}>{fmtMD(sel.iso)}</p>
                  <button onClick={() => setSel(null)}
                    className="text-slate-300 hover:text-slate-500 transition"
                    style={{ fontSize: '13px', lineHeight: 1 }} aria-label="닫기">×</button>
                </div>
                <div className="flex flex-col" style={{ gap: '4px' }}>
                  {selEvents.map(ev => (
                    <div key={ev.id}>
                      <p className="text-slate-700 leading-snug" style={{ fontSize: '11px' }}>{ev.event}</p>
                      <p className="text-slate-400" style={{ fontSize: '10px' }}>{fmtRange(ev.start_date, ev.end_date)}</p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* 다가오는 일정 — 항상 고정 */}
        <div className="border-t border-slate-100" style={{ marginTop: '8px', paddingTop: '8px' }}>
          <p className="text-slate-400" style={{ fontSize: '10px', fontWeight: 700, marginBottom: '5px' }}>{t.upcoming}</p>
          {upcoming.length === 0 ? (
            <p className="text-slate-300" style={{ fontSize: '11px' }}>{t.none}</p>
          ) : (
            <div className="flex flex-col" style={{ gap: '4px' }}>
              {upcoming.map(ev => (
                <div key={ev.id} className="flex items-start" style={{ gap: '6px' }}>
                  <span className="shrink-0 rounded text-[#005956] bg-[#005956]/10 text-center"
                    style={{ fontSize: '10px', fontWeight: 700, padding: '1px 4px', minWidth: '34px' }}>
                    {fmtMD(ev.start_date)}
                  </span>
                  <span className="text-slate-600 leading-snug" style={{ fontSize: '11px' }}>{ev.event}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
