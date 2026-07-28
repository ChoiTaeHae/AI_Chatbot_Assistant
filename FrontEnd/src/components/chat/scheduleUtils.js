// 학사일정 달력 공통 로직 — ScheduleCard(채팅 답변 카드)와 ScheduleWidget(사이드바)이 공유한다.
// 예전엔 ScheduleCard에만 있어서 위젯이 점만 찍었고, 복붙하면 팔레트·세그먼트 규칙이 따로 놀 위험이 있었다.

export const WD = ['일', '월', '화', '수', '목', '금', '토']

export function toISO(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const da = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${da}`
}

export function fmtDate(s) {
  return `${Number(s.slice(5, 7))}월 ${Number(s.slice(8, 10))}일`
}

// 카테고리별 색 — 일정 '종류'가 곧 색이므로 DB에 색을 저장하지 않고 이름으로 결정한다.
// (같은 종류는 항상 같은 색이 보장되고, 새 일정을 크롤해 넣어도 색 지정 작업이 필요 없다)
// 관리자 달력과 동일 팔레트.
export function catStyle(e) {
  if (/수강|정정|철회|변경/.test(e)) return 'bg-blue-100 text-blue-700'
  if (/성적|평가|시험/.test(e)) return 'bg-purple-100 text-purple-700'
  if (/등록|납부|분납|장학/.test(e)) return 'bg-emerald-100 text-emerald-700'
  if (/휴학|복학|자퇴|전과|재입학/.test(e)) return 'bg-amber-100 text-amber-700'
  if (/졸업|학위|입학/.test(e)) return 'bg-rose-100 text-rose-700'
  if (/방학|개강|종강|개학|공휴일|연휴/.test(e)) return 'bg-(--border) text-(--text-body)'
  return 'bg-(--surface-2) text-(--text-muted)'
}

// 좁은 사이드바용 — 텍스트 없이 '색 막대'만 그린다.
// Tailwind -300은 색상마다 채도가 제각각(amber는 쨍, violet은 차분)이라 조화가 깨진다.
// → 명도·채도를 통일한 마카롱 파스텔 세트를 직접 지정해 '색상(hue)만' 다르게 한다.
export function catBar(e) {
  if (/수강|정정|철회|변경/.test(e)) return 'bg-[#A8CCE8]'   // 소프트 블루
  if (/성적|평가|시험/.test(e)) return 'bg-[#C4B8E0]'         // 소프트 라벤더
  if (/등록|납부|분납|장학/.test(e)) return 'bg-[#A8D8C0]'    // 소프트 민트
  if (/휴학|복학|자퇴|전과|재입학/.test(e)) return 'bg-[#F3CBA8]' // 소프트 피치
  if (/졸업|학위|입학/.test(e)) return 'bg-[#F0BAC8]'         // 소프트 로즈
  if (/방학|개강|종강|개학|공휴일|연휴/.test(e)) return 'bg-[#C2D6A8]' // 소프트 세이지
  return 'bg-(--border-strong)'                                       // 소프트 그레이
}

// 한 달을 감싸는 주 배열(일요일 시작). 항상 6줄 고정 → 달마다 높이가 일정해져
// 페이지를 넘겨도(화살표) 세로 중앙의 버튼 위치가 안 바뀐다.
export function buildMonthWeeks(year, month0) {
  const first = new Date(year, month0, 1)
  const cur = new Date(first)
  cur.setDate(1 - first.getDay())
  const weeks = []
  for (let w = 0; w < 6; w++) {
    const week = []
    for (let i = 0; i < 7; i++) { week.push(new Date(cur)); cur.setDate(cur.getDate() + 1) }
    weeks.push(week)
  }
  return weeks
}

// 한 주에 걸치는 일정 → 연속 막대 세그먼트 + lane(겹칠 때 위아래로 쌓기).
// roundedLeft/Right: 주 경계에서 잘린 쪽은 각지게 둬 '이어짐'을 시각적으로 표현한다.
export function segsForWeek(days, events) {
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
