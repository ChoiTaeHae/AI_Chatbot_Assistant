import { useState, useEffect } from 'react'
import { getWeekCafeteria, getMySessions, getGraduationReport } from '../../api/chat'

const T = {
  ko: { newChat: '새 대화', meal: '학생식단', recent: '최근 대화', all: '전체', empty: '아직 대화가 없어요', noMeal: '이번 주 학식 정보가 없어요', credit: '학점 진행률', toGrad: '졸업까지', earned: '총 이수',
        detail: '자세히', collapse: '접기', sample: ' · 예시', unit: '학점', met: '충족', totalLabel: '총 이수학점',
        shortMsg: (n) => `${n}학점 부족`, remainMsg: (n) => `졸업까지 ${n}학점 남음`, classOf: (yy) => `${yy}학번`,
        note: '※ 학점 기준이에요. 졸업시험·영어인증 등은 별도로 확인하세요.' },
  en: { newChat: 'New chat', meal: 'Cafeteria', recent: 'Recent', all: 'All', empty: 'No conversations yet', noMeal: 'No menu this week', credit: 'Credit Progress', toGrad: 'To graduate', earned: 'Earned',
        detail: 'Details', collapse: 'Collapse', sample: ' · sample', unit: ' credits', met: 'Met', totalLabel: 'Total earned',
        shortMsg: (n) => `${n} credits short`, remainMsg: (n) => `${n} credits left to graduate`, classOf: (yy) => `Class of '${yy}`,
        note: '※ Credits only. Check graduation exam / English certification separately.' },
  zh: { newChat: '新对话', meal: '学生食堂', recent: '最近对话', all: '全部', empty: '还没有对话', noMeal: '本周暂无菜单', credit: '学分进度', toGrad: '距毕业', earned: '已修',
        detail: '详情', collapse: '收起', sample: ' · 示例', unit: '学分', met: '已满足', totalLabel: '总修学分',
        shortMsg: (n) => `还差${n}学分`, remainMsg: (n) => `距毕业还剩${n}学分`, classOf: (yy) => `${yy}级`,
        note: '※ 仅按学分计算。毕业考试、英语认证等请另行确认。' },
}

// 관리자 페이지 Topic 관리에 등록된 실제 20개 topic (2026-07-14 기준)
const TOPIC_LABELS = {
  ko: {
    campus: '캠퍼스', graduation: '졸업요건', scholarship: '장학금', general: '일반대화',
    schedule: '학사일정', leave: '휴학/복학', dormitory: '기숙사',
    course_registration: '수강신청', grades: '성적', school_rules: '학칙/규정', absence: '공결',
    student_support: '학생지원', rotc: 'ROTC/학군단', rag_general: '일반학사',
    graduate_school: '대학원', major_change: '전공변경', facility_rental: '시설대여',
    parking: '주차안내', welfare_facilities: '복지시설', college_department: '학부/학과',
  },
  en: {
    campus: 'Campus', graduation: 'Graduation', scholarship: 'Scholarship', general: 'General',
    schedule: 'Schedule', leave: 'Leave/Return', dormitory: 'Dorm',
    course_registration: 'Enrollment', grades: 'Grades', school_rules: 'School Rules', absence: 'Absence',
    student_support: 'Support', rotc: 'ROTC', rag_general: 'Academic (Gen.)',
    graduate_school: 'Grad School', major_change: 'Major Change', facility_rental: 'Facility Rental',
    parking: 'Parking', welfare_facilities: 'Welfare', college_department: 'Colleges',
  },
  zh: {
    campus: '校园', graduation: '毕业要求', scholarship: '奖学金', general: '闲聊',
    schedule: '校历', leave: '休学/复学', dormitory: '宿舍',
    course_registration: '选课', grades: '成绩', school_rules: '校规', absence: '公假',
    student_support: '学生支持', rotc: 'ROTC军训团', rag_general: '一般学务',
    graduate_school: '研究生院', major_change: '转专业', facility_rental: '设施租赁',
    parking: '停车', welfare_facilities: '福利设施', college_department: '学部/学科',
  },
}
const topicLabel = (tp, lang = 'ko') => {
  const labels = TOPIC_LABELS[lang] || TOPIC_LABELS.ko
  return labels[tp] || labels.general
}

// 식당명 언어별 표기 (실 API는 크롤링된 한국어 이름만 내려주므로, 매핑에 없으면 원본 그대로 폴백)
const RESTAURANT_NAMES = {
  '학생식당(서캠)': { en: 'Student Cafeteria (West)', zh: '学生食堂（西校区）' },
  '학생식당(동캠)': { en: 'Student Cafeteria (East)', zh: '学生食堂（东校区）' },
  '기숙사식당': { en: 'Dormitory Cafeteria', zh: '宿舍食堂' },
}
const restaurantName = (name, lang = 'ko') => (lang !== 'ko' && RESTAURANT_NAMES[name]?.[lang]) || name

// 위치 정보 언어별 표기 (실 API는 위치 데이터를 안 주므로 샘플 전용 — 매핑 없으면 원본 폴백)
const LOCATION_NAMES = {
  '서캠퍼스 학생회관 1층': { en: '1F, Student Union, West Campus', zh: '西校区学生会馆1楼' },
  '동캠퍼스 테크노디자인센터 지하': { en: 'Basement, Techno Design Center, East Campus', zh: '东校区科技设计中心地下' },
  '국제기숙사 · 청운숙기숙사 · 기숙사(동캠)': { en: 'International Dorm · Cheongwoonsuk Dorm · Dormitory (East)', zh: '国际宿舍 · 青云宿舍 · 宿舍（东校区）' },
}
const locationName = (loc, lang = 'ko') => (lang !== 'ko' && LOCATION_NAMES[loc]?.[lang]) || loc

// 학점 진행률 카테고리명 언어별 표기 (실 API가 한글 이름만 주므로 매핑 없으면 원본 폴백).
// '일반'은 백엔드가 그대로 '일반'으로 내려주되 화면 표기만 '일선'으로 바꾼다(요청).
// '다전공'은 복수전공 이수 학점 — 백엔드가 categories에 담아 보내면 이 라벨로 표시된다.
const CATEGORY_NAMES = {
  '전공':   { ko: '전공',   en: 'Major',             zh: '专业' },
  '교양':   { ko: '교양',   en: 'General Education',  zh: '通识' },
  '다전공': { ko: '다전공', en: 'Multi-major',        zh: '多专业' },
  '일반':   { ko: '일선',   en: 'General Elective',   zh: '一般选修' },
}
const categoryName = (name, lang = 'ko') => CATEGORY_NAMES[name]?.[lang] || name

// 학생식당 코너(소담상·덮밥·교직원 등)를 끼니(조식/중식/석식)로 묶는다.
// 학생식당은 학기중 여러 코너가 전부 '점심'에 열리므로 카드가 너무 길어져, 중식 하나로
// 접고 '자세히'로 펼친다. 천원의아침밥→조식, 조/중/석 컬럼은 그대로(기숙사), 그 외 코너는
// 전부 중식으로 본다. 학교가 코너명을 바꿔도 '모르는 코너=중식' 기본값이라 최소한 중식엔 계속 노출.
const _MEAL_ORDER = ['조식', '중식', '석식']
function mealBucket(cornerName) {
  if (cornerName.includes('아침') || cornerName === '조식') return '조식'
  if (cornerName === '석식') return '석식'
  return '중식'
}
function groupMeals(meals) {
  const map = {}
  for (const m of meals) {
    const b = mealBucket(m.name)
    ;(map[b] = map[b] || []).push(m)
  }
  return _MEAL_ORDER.filter((b) => map[b]).map((b) => ({ meal: b, corners: map[b] }))
}

// ── 시연용 더미 (실데이터 없을 때 fallback) ──
const SAMPLE_CREDIT = {
  dept_name: '소프트웨어학과', student_no: '20221234',
  total_earned: 115, total_required: 145, remaining: 30,
  categories: [
    { name: '전공', earned: 58, required: 66 },
    { name: '교양', earned: 27, required: 30 },
    { name: '다전공', earned: 12, required: 21 },   // 복수전공 이수 학점 (샘플)
    { name: '일반', earned: 18, required: 28 },       // 표기는 '일선'으로 나감
  ],
}
// 학생식당(서캠/동캠)은 월~금만, 기숙사식당은 토·일까지 7일 전체 사용
const WEEKDAY = {
  ko: ['일', '월', '화', '수', '목', '금', '토'],
  en: ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'],
  zh: ['日', '一', '二', '三', '四', '五', '六'],
}
function weekdayOf(mmdd, lang = 'ko') {
  try {
    const [m, d] = mmdd.split('.').map(Number)
    const idx = new Date(new Date().getFullYear(), m - 1, d).getDay()   // 0=일 ~ 6=토
    return (WEEKDAY[lang] || WEEKDAY.ko)[idx] ?? ''
  } catch { return '' }
}
function fmtMMDD(dt) {
  return `${String(dt.getMonth() + 1).padStart(2, '0')}.${String(dt.getDate()).padStart(2, '0')}`
}
const mmddToday = () => fmtMMDD(new Date())
// 이번 주 날짜 (샘플이 항상 이번 주로 보이도록 동적 생성)
function thisWeekDates(count) {
  const now = new Date()
  const monday = new Date(now)
  monday.setDate(now.getDate() - ((now.getDay() + 6) % 7))
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(monday); d.setDate(monday.getDate() + i); return fmtMMDD(d)
  })
}
const thisWeekMonToFri = () => thisWeekDates(5)   // 학생식당(서캠/동캠): 월~금
const thisWeekMonToSun = () => thisWeekDates(7)   // 기숙사식당: 월~일(매일 운영)

// ── 시연용 학식 샘플 (실데이터 없을 때 fallback) ──
// 참고: 실제 학식 API는 메뉴 항목만 제공. 위치/가격은 데모용 샘플 값이다.
const _WD = thisWeekMonToFri()
const _WD7 = thisWeekMonToSun()
const SAMPLE_WEEK = {
  restaurants: [
    // 학생식당(서캠/동캠): 실제 크롤 구조 그대로 — 천원의아침밥(조식) + 여러 점심 코너.
    // 학기중엔 코너가 자율주문(급식 아님)이라 끼니 대신 코너로 나뉘어서, 위젯이 점심 코너들을
    // '중식' 하나로 묶어 '자세히'로 펼친다. 실 API엔 가격이 없어 price 미표기.
    {
      name: '학생식당(서캠)', location: '서캠퍼스 학생회관 1층',
      days: [
        { date: _WD[0], meals: [{ name: '천원의아침밥', items: ['백미밥', '북어해장국', '계란말이'] }, { name: '소담상', items: ['제육볶음', '계란국', '쌈채소', '겉절이'] }, { name: '속이찬새참', items: ['참치마요덮밥', '유부된장국', '단무지'] }, { name: '덮밥', items: ['마파두부덮밥', '미소국', '치킨너겟'] }, { name: '바삭카츠', items: ['등심돈까스', '양배추샐러드', '크림스프'] }, { name: '교직원', items: ['갈비탕', '잡곡밥', '도라지무침', '배추김치'] }] },
        { date: _WD[1], meals: [{ name: '천원의아침밥', items: ['흑미밥', '시래기국', '어묵볶음'] }, { name: '소담상', items: ['비빔밥', '된장국', '깍두기'] }, { name: '속이찬새참', items: ['김치볶음밥', '어묵맑은국', '단무지'] }, { name: '덮밥', items: ['오징어덮밥', '유부장국', '군만두'] }, { name: '바삭카츠', items: ['치즈돈까스', '양배추샐러드', '콘스프'] }, { name: '교직원', items: ['육개장', '수수밥', '고사리무침', '배추김치'] }] },
        { date: _WD[2], meals: [{ name: '천원의아침밥', items: ['백미밥', '콩나물국', '스크램블에그'] }, { name: '소담상', items: ['김치찌개', '계란말이', '김'] }, { name: '속이찬새참', items: ['새우볶음밥', '짬뽕국', '단무지'] }, { name: '덮밥', items: ['제육덮밥', '미소된장국', '치킨텐더'] }, { name: '바삭카츠', items: ['생선까스', '타르타르소스', '양배추샐러드'] }, { name: '교직원', items: ['삼계탕', '찰밥', '부추무침', '열무김치'] }] },
        { date: _WD[3], meals: [{ name: '천원의아침밥', items: ['기장밥', '감자국', '비엔나볶음'] }, { name: '소담상', items: ['카레라이스', '샐러드', '피클'] }, { name: '속이찬새참', items: ['불고기덮밥', '유부장국', '단무지'] }, { name: '덮밥', items: ['규동', '미소국', '핫도그'] }, { name: '바삭카츠', items: ['등심돈까스', '양배추샐러드', '크림스프'] }, { name: '교직원', items: ['뚝배기불고기', '잡곡밥', '도토리묵무침', '배추김치'] }] },
        { date: _WD[4], meals: [{ name: '천원의아침밥', items: ['백미밥', '미역국', '계란찜'] }, { name: '소담상', items: ['짜장밥', '군만두', '단무지'] }, { name: '속이찬새참', items: ['오므라이스', '양송이스프', '피클'] }, { name: '덮밥', items: ['치킨마요덮밥', '유부장국', '군만두'] }, { name: '바삭카츠', items: ['고구마치즈까스', '양배추샐러드', '콘스프'] }, { name: '교직원', items: ['아귀찜', '쌀밥', '콩나물무침', '배추김치'] }] },
      ],
    },
    {
      name: '학생식당(동캠)', location: '동캠퍼스 테크노디자인센터 지하',
      days: [
        { date: _WD[0], meals: [{ name: '천원의아침밥', items: ['백미밥', '미소된장국', '스크램블에그'] }, { name: '한식', items: ['돈까스', '우동', '단무지'] }, { name: '푸드코트', items: ['짜장면', '미니탕수육', '단무지'] }] },
        { date: _WD[1], meals: [{ name: '천원의아침밥', items: ['흑미밥', '북어국', '어묵볶음'] }, { name: '한식', items: ['제육쌈밥', '미역국', '겉절이'] }, { name: '푸드코트', items: ['돈까스', '크림파스타', '피클'] }] },
        { date: _WD[2], meals: [{ name: '천원의아침밥', items: ['백미밥', '콩나물국', '계란말이'] }, { name: '한식', items: ['순두부찌개', '계란찜', '김치'] }, { name: '푸드코트', items: ['비빔밥', '유부장국', '야채튀김'] }] },
        { date: _WD[3], meals: [{ name: '천원의아침밥', items: ['기장밥', '감자국', '비엔나볶음'] }, { name: '한식', items: ['비프카레', '샐러드', '깍두기'] }, { name: '푸드코트', items: ['우동', '유부초밥', '단무지'] }] },
        { date: _WD[4], meals: [{ name: '천원의아침밥', items: ['백미밥', '시래기국', '계란찜'] }, { name: '한식', items: ['짬뽕밥', '군만두', '단무지'] }, { name: '푸드코트', items: ['치킨마요덮밥', '미소국', '피클'] }] },
      ],
    },
    // 기숙사식당: 국제기숙사/청운숙기숙사/기숙사(동캠) 3곳 모두 메뉴 동일 → 위치란에 3곳 이름 표기
    // 기숙사생은 매일 식사하므로 학생식당과 달리 토·일 포함 7일 전체 제공
    {
      name: '기숙사식당', location: '국제기숙사 · 청운숙기숙사 · 기숙사(동캠)',
      days: [
        { date: _WD7[0], meals: [{ name: '조식', items: ['북엇국', '계란후라이', '김', '쌀밥'] }, { name: '중식', items: ['치킨가스', '크림스프', '피클'] }, { name: '석식', items: ['소불고기', '미역국', '나물무침'] }] },
        { date: _WD7[1], meals: [{ name: '조식', items: ['된장국', '스크램블에그', '깍두기', '쌀밥'] }, { name: '중식', items: ['제육덮밥', '어묵국', '단무지'] }, { name: '석식', items: ['생선까스', '콩나물국', '겉절이'] }] },
        { date: _WD7[2], meals: [{ name: '조식', items: ['시래기국', '계란말이', '김치', '쌀밥'] }, { name: '중식', items: ['김치볶음밥', '유부장국', '단무지'] }, { name: '석식', items: ['닭갈비', '미소국', '쌈채소'] }] },
        { date: _WD7[3], meals: [{ name: '조식', items: ['콩나물국', '햄구이', '김', '쌀밥'] }, { name: '중식', items: ['카레라이스', '샐러드', '피클'] }, { name: '석식', items: ['돼지갈비찜', '두부된장국', '나물'] }] },
        { date: _WD7[4], meals: [{ name: '조식', items: ['미역국', '계란후라이', '깍두기', '쌀밥'] }, { name: '중식', items: ['불닭덮밥', '계란국', '단무지'] }, { name: '석식', items: ['고등어구이', '된장국', '김치'] }] },
        { date: _WD7[5], meals: [{ name: '조식', items: ['감자국', '소시지구이', '깍두기', '쌀밥'] }, { name: '중식', items: ['부대찌개', '계란말이', '단무지'] }, { name: '석식', items: ['돈까스', '미역국', '쌈채소'] }] },
        { date: _WD7[6], meals: [{ name: '조식', items: ['황태국', '계란찜', '김', '쌀밥'] }, { name: '중식', items: ['비빔밥', '된장국', '나물'] }, { name: '석식', items: ['삼겹살구이', '김치찌개', '겉절이'] }] },
      ],
    },
  ],
}
const SAMPLE_SESSIONS = [
  { id: -1, title: '수강신청 기간 언제야?', topic: 'course_registration' },
  { id: -2, title: '학생회관 어디야?', topic: 'campus' },
  { id: -3, title: '휴학 어떻게 신청해?', topic: 'leave' },
  { id: -4, title: '졸업 요건 알려줘', topic: 'graduation' },
  { id: -5, title: '장학금 종류 뭐 있어?', topic: 'scholarship' },
  { id: -6, title: '기숙사 신청 방법 알려줘', topic: 'dormitory' },
  { id: -7, title: '공결 신청하고 싶어', topic: 'absence' },
  { id: -8, title: '성적 이의신청 어떻게 해?', topic: 'grades' },
  { id: -9, title: '학생회관 시설대여 방법', topic: 'facility_rental' },
  { id: -10, title: '기숙사 주차 가능해?', topic: 'parking' },
  { id: -11, title: '학생지원 프로그램 뭐 있어', topic: 'student_support' },
  { id: -12, title: '학칙 위반하면 어떻게 돼?', topic: 'school_rules' },
  { id: -13, title: 'ROTC 지원 자격이 어떻게 돼?', topic: 'rotc' },
  { id: -14, title: '대학원 진학 상담받고 싶어', topic: 'graduate_school' },
  { id: -15, title: '전공 변경 신청 기간', topic: 'major_change' },
  { id: -16, title: '학생식당 위치가 어디야?', topic: 'welfare_facilities' },
  { id: -17, title: '학사일정 언제 나와?', topic: 'schedule' },
  { id: -18, title: '학부/학과 소개해줘', topic: 'college_department' },
  { id: -19, title: '자격증 취득하면 학점 인정돼?', topic: 'rag_general' },
  { id: -20, title: '안녕!', topic: 'general' },
]

export default function Sidebar({ lang = 'ko', role, onNewChat, onSelectSession, activeSessionId, onSessionDeleted }) {
  const t = T[lang] || T.ko
  const [credit, setCredit] = useState(null)
  const [creditSample, setCreditSample] = useState(false)
  const [mealSample, setMealSample] = useState(false)
  const [sessions, setSessions] = useState([])
  const [sessionsSample, setSessionsSample] = useState(false)
  const [filter, setFilter] = useState('all')
  const [creditModal, setCreditModal] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)   // 삭제 확인 대상 세션
  const [week, setWeek] = useState(null)
  const [restIdx, setRestIdx] = useState(0)   // 선택된 식당(캐러셀)
  const [dayIdx, setDayIdx] = useState(0)      // 선택된 요일 탭
  const [openMeals, setOpenMeals] = useState({})   // 펼친 끼니 그룹 {중식: true}

  useEffect(() => {
    // 학점 진행률은 학생만 — 관리자·비학생은 아예 조회/표시 안 함
    if (role === 'student') {
      getGraduationReport()
        .then((d) => {
          if (d?.available) { setCredit(d); setCreditSample(false) }
          else { setCredit(SAMPLE_CREDIT); setCreditSample(true) }  // 학생인데 데이터 없음 → 시연용 샘플
        })
        .catch(() => { setCredit(SAMPLE_CREDIT); setCreditSample(true) })
    }
    // role !== 'student'(관리자 등)는 credit 초기값(null)이 유지되어 위젯이 자동으로 숨겨짐

    getWeekCafeteria()
      .then((d) => ((d?.available && d.restaurants?.length) ? d : SAMPLE_WEEK))
      .catch(() => SAMPLE_WEEK)
      .then((data) => {
        setWeek(data); setMealSample(data === SAMPLE_WEEK)
        // 오늘 요일 탭을 기본 선택 (API 실패로 샘플 fallback일 때도 동일 적용)
        const days = data.restaurants[0]?.days || []
        const idx = days.findIndex((x) => x.date === mmddToday())
        if (idx >= 0) setDayIdx(idx)
      })

    getMySessions()
      .then((list) => {
        if (list?.length) {
          // DB에 topic 값이 앞뒤 공백과 함께 저장된 경우가 있어 (예: " graduate_school")
          // trim 없이 비교하면 TOPIC_LABELS에 매칭이 안 되고 '일반대화'로 잘못 표시된다.
          setSessions(list.map((s) => ({ ...s, topic: s.topic?.trim() || s.topic })))
          setSessionsSample(false)
        }
        else { setSessions(SAMPLE_SESSIONS); setSessionsSample(true) }
      })
      .catch(() => { setSessions(SAMPLE_SESSIONS); setSessionsSample(true) })
  }, [role])

  const presentTopics = Array.from(new Set(sessions.map((s) => s.topic).filter(Boolean)))
  const filtered = filter === 'all' ? sessions : sessions.filter((s) => s.topic === filter)

  // 식당 전환: 요일 탭을 월요일(0)로 리셋하지 않고 오늘 요일 유지
  function selectRestaurant(i) {
    setRestIdx(i)
    setOpenMeals({})   // 식당 바뀌면 펼친 끼니 접기
    const days = (week?.restaurants || [])[i]?.days || []
    const idx = days.findIndex((x) => x.date === mmddToday())
    setDayIdx(idx >= 0 ? idx : 0)
  }

  // 대화 삭제: 확인 모달에서 최종 승인 시 로컬 목록에서 제거 (실제 영구 삭제는 백엔드 DELETE 엔드포인트 필요)
  function confirmDeleteSession() {
    if (!deleteTarget) return
    const id = deleteTarget.id
    setSessions((prev) => prev.filter((x) => x.id !== id))
    if (id === activeSessionId) onSessionDeleted?.(id)
    setDeleteTarget(null)
  }

  // 학식: 선택된 식당/요일 파생값
  const restaurants = week?.restaurants || []
  const rest = restaurants[Math.min(restIdx, Math.max(0, restaurants.length - 1))] || null
  const days = rest?.days || []
  const curDay = days[Math.min(dayIdx, Math.max(0, days.length - 1))] || null

  return (
    <>
    <aside className="flex flex-col w-[264px] h-full bg-white rounded-2xl border border-slate-200 shadow-lg overflow-hidden">
      <div className="flex flex-col h-full" style={{ padding: '14px 12px' }}>

        {/* 새 대화 */}
        <button
          onClick={onNewChat}
          className="flex items-center justify-center gap-2 rounded-xl text-sm font-semibold text-white bg-[#005956] hover:bg-[#004d4a] transition shrink-0"
          style={{ padding: '12px' }}
        >
          <svg viewBox="0 0 20 20" width="15" height="15" fill="none" aria-hidden="true"><path d="M10 4v12M4 10h12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
          {t.newChat}
        </button>

        {/* 학점 진행률 (남은 학점만 · 백분율 없음) */}
        {credit && (
          <section className="border border-slate-200 rounded-xl bg-white shrink-0" style={{ padding: '12px', marginTop: '14px' }}>
            <div className="flex items-center justify-between" style={{ marginBottom: '8px' }}>
              <span className="text-xs font-bold text-slate-800">🎓 {t.credit}{creditSample && <span className="text-slate-400 font-medium">{t.sample}</span>}</span>
              <button onClick={() => setCreditModal(true)} className="font-semibold text-[#005956] hover:underline" style={{ fontSize: '11px' }}>{t.detail}</button>
            </div>
            <p className="text-slate-400" style={{ fontSize: '11px' }}>{t.toGrad}</p>
            <p className="font-extrabold text-[#005956]" style={{ fontSize: '22px', lineHeight: 1.1 }}>{credit.remaining}{t.unit}</p>
            <p className="text-slate-500" style={{ fontSize: '11px', marginTop: '5px' }}>
              {t.earned} {credit.total_earned} / {credit.total_required}{t.unit}
            </p>
            {credit.dept_name && (
              <p className="text-slate-400" style={{ fontSize: '11px', marginTop: '2px' }}>
                {credit.dept_name}{credit.student_no ? ` · ${t.classOf(credit.student_no.slice(2, 4))}` : ''}
              </p>
            )}
          </section>
        )}

        {/* 학생식단 */}
        <section className="border border-slate-200 rounded-xl bg-white shrink-0 overflow-hidden" style={{ marginTop: '14px' }}>
          <div style={{ padding: '12px' }}>
            {/* 헤더: 제목 + 식당 선택 */}
            <div className="flex items-center justify-between" style={{ marginBottom: rest?.location ? '4px' : '10px' }}>
              <span className="text-xs font-bold text-slate-800">🍱 {t.meal}{mealSample && <span className="text-slate-400 font-medium">{t.sample}</span>}</span>
              {restaurants.length > 0 && (
                <select
                  value={restIdx}
                  onChange={(e) => selectRestaurant(Number(e.target.value))}
                  className="border border-slate-200 rounded-lg text-slate-600 bg-white outline-none cursor-pointer hover:border-[#005956]/40"
                  style={{ padding: '3px 6px', maxWidth: '118px', fontSize: '11px' }}
                >
                  {restaurants.map((r, i) => <option key={r.name} value={i}>{restaurantName(r.name, lang)}</option>)}
                </select>
              )}
            </div>

            {rest ? (
              <>
                {/* 위치 */}
                {rest.location && (
                  <p className="flex items-center gap-1 text-slate-400" style={{ fontSize: '11px', marginBottom: '10px' }}>
                    <span>📍</span>{locationName(rest.location, lang)}
                  </p>
                )}

                {/* 요일 탭 */}
                {days.length > 0 && (
                  <div className="flex gap-1" style={{ marginBottom: '12px' }}>
                    {days.map((d, i) => (
                      <button
                        key={d.date}
                        onClick={() => { setDayIdx(i); setOpenMeals({}) }}
                        className={`flex-1 rounded-lg text-xs font-semibold transition ${
                          i === dayIdx ? 'bg-[#005956] text-white' : 'text-slate-500 hover:bg-slate-100'
                        }`}
                        style={{ padding: '3px 0' }}
                      >
                        {weekdayOf(d.date, lang)}
                      </button>
                    ))}
                  </div>
                )}

                {/* 끼니 카드 (시간 제외) — 학생식당 코너는 중식으로 묶어 '자세히'로 펼침 */}
                {curDay?.meals?.length ? groupMeals(curDay.meals).map((g, gi) => {
                  const wrapStyle = {
                    marginTop: gi === 0 ? '0' : '10px',
                    paddingTop: gi === 0 ? '0' : '10px',
                    borderTop: gi === 0 ? 'none' : '1px solid #f1f5f9',
                  }
                  // 코너 1개 → 일반 카드 (기숙사 조/중/석, 천원의아침밥, 샘플 중식)
                  if (g.corners.length === 1) {
                    const c = g.corners[0]
                    // 천원의아침밥 같은 조식 프로그램만 코너명 유지, 그 외 단일 코너는 끼니명으로 표시.
                    // (계절학기에 교직원식당만 있을 때 '교직원' 대신 '중식'으로 보이게)
                    const title = c.name.includes('아침') ? c.name : g.meal
                    return (
                      <div key={g.meal} style={wrapStyle}>
                        <span className="text-sm font-bold text-[#005956]">{title}</span>
                        <p className="text-slate-600" style={{ fontSize: '12px', marginTop: '4px', lineHeight: 1.5 }}>{c.items.join(', ')}</p>
                        {c.price && <p className="text-right font-bold text-slate-800" style={{ fontSize: '13px', marginTop: '4px' }}>{c.price}</p>}
                      </div>
                    )
                  }
                  // 코너 여러 개 → 접힌 끼니 카드 + 자세히
                  const opened = !!openMeals[g.meal]
                  return (
                    <div key={g.meal} style={wrapStyle}>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-bold text-[#005956]">{g.meal}</span>
                        <button
                          onClick={() => setOpenMeals((p) => ({ ...p, [g.meal]: !p[g.meal] }))}
                          className="shrink-0 inline-flex items-center gap-1 font-bold text-[#005956] bg-[#005956]/10 hover:bg-[#005956]/15 rounded-full transition"
                          style={{ fontSize: '11px', padding: '3px 9px' }}
                        >
                          {opened ? t.collapse : t.detail}
                          <span style={{ display: 'inline-block', transform: opened ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }}>⌄</span>
                        </button>
                      </div>
                      {!opened && (
                        <p className="text-slate-400" style={{ fontSize: '11px', marginTop: '4px', lineHeight: 1.5 }}>
                          {g.corners.map((c) => c.name).join(' · ')}
                        </p>
                      )}
                      {opened && (
                        <div style={{ marginTop: '8px' }}>
                          {g.corners.map((c, ci) => (
                            <div
                              key={c.name}
                              style={{
                                marginTop: ci === 0 ? '0' : '8px',
                                paddingTop: ci === 0 ? '0' : '8px',
                                borderTop: ci === 0 ? 'none' : '1px dashed #e2e8f0',
                              }}
                            >
                              <span className="font-bold text-[#0f766e]" style={{ fontSize: '12.5px' }}>{c.name}</span>
                              <p className="text-slate-600" style={{ fontSize: '12px', marginTop: '2px', lineHeight: 1.5 }}>{c.items.join(', ')}</p>
                              {c.price && <p className="text-right font-bold text-slate-800" style={{ fontSize: '13px', marginTop: '4px' }}>{c.price}</p>}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                }) : (
                  <p className="text-xs text-slate-400">{t.noMeal}</p>
                )}
              </>
            ) : (
              <p className="text-xs text-slate-400">{t.noMeal}</p>
            )}
          </div>
        </section>

        {/* 최근 대화 + topic 필터 */}
        <div className="flex flex-col min-h-0 flex-1" style={{ marginTop: '16px' }}>
          <div className="flex items-center justify-between shrink-0" style={{ marginBottom: '8px', padding: '0 2px' }}>
            <span className="text-slate-400 font-semibold uppercase tracking-wide" style={{ fontSize: '11px' }}>
              {t.recent}{sessionsSample && t.sample}
            </span>
            {presentTopics.length > 0 && (
              <select
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                className="text-xs border border-slate-200 rounded-lg text-slate-600 bg-white outline-none cursor-pointer hover:border-[#005956]/40"
                style={{ padding: '3px 6px' }}
              >
                <option value="all">{t.all}</option>
                {presentTopics.map((tp) => <option key={tp} value={tp}>{topicLabel(tp, lang)}</option>)}
              </select>
            )}
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto">
            {filtered.length === 0 ? (
              <p className="text-xs text-slate-400" style={{ padding: '8px' }}>{t.empty}</p>
            ) : filtered.map((s) => {
              const active = s.id === activeSessionId
              return (
                <div
                  key={s.id}
                  className={`group relative rounded-lg transition border ${
                    active
                      ? 'bg-[#005956]/10 border-[#005956]/25 shadow-sm'
                      : 'border-transparent hover:bg-[#005956]/8 hover:border-[#005956]/20'
                  }`}
                  style={{ marginBottom: '2px' }}
                >
                  <button
                    onClick={() => s.id > 0 && onSelectSession?.(s.id)}
                    className={`w-full flex items-center gap-1 text-left truncate transition ${
                      active ? 'text-[#005956] font-medium' : 'text-slate-600 group-hover:text-[#005956]'
                    }`}
                    style={{ padding: '7px 30px 7px 0px', fontSize: '13px' }}
                  >
                    <span className="shrink-0">💬</span>
                    <span className="truncate">{s.title}</span>
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); setDeleteTarget(s) }}
                    aria-label="대화 삭제"
                    title="삭제"
                    className="absolute top-1/2 -translate-y-1/2 flex items-center justify-center rounded-md text-slate-400 opacity-0 group-hover:opacity-100 hover:bg-red-50 hover:text-red-500 transition"
                    style={{ right: '4px', width: '22px', height: '22px' }}
                  >
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </aside>

    {/* 학점 진행률 자세히 — 항목별 (백분율 없음, 학점 기준) */}
    {creditModal && credit && (
      <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(15,23,42,.5)', padding: '16px' }} onClick={() => setCreditModal(false)}>
        <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden" style={{ maxHeight: '85vh' }} onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between border-b border-slate-100" style={{ padding: '16px 18px' }}>
            <div>
              <p className="text-slate-400" style={{ fontSize: '11px' }}>{credit.dept_name}{credit.student_no ? ` · ${t.classOf(credit.student_no.slice(2, 4))}` : ''}</p>
              <p className="font-bold text-slate-800" style={{ fontSize: '16px' }}>🎓 {t.credit}</p>
            </div>
            <button onClick={() => setCreditModal(false)} className="text-slate-400 hover:text-slate-700 text-lg" aria-label="닫기">✕</button>
          </div>
          <div style={{ padding: '18px', overflowY: 'auto' }}>
            {(credit.categories || []).map((c) => {
              const short = Math.max(0, c.required - c.earned)
              const pct = c.required > 0 ? Math.min(100, (c.earned / c.required) * 100) : 100
              const met = short === 0
              return (
                <div key={c.name} style={{ marginBottom: '14px' }}>
                  <div className="flex items-center justify-between" style={{ marginBottom: '6px' }}>
                    <span className="text-sm font-semibold text-slate-700">{categoryName(c.name, lang)}</span>
                    <span className="text-sm font-bold text-slate-800">{c.earned} <span className="text-slate-400 font-medium">/ {c.required}</span></span>
                  </div>
                  <div className="rounded-full bg-slate-100 overflow-hidden" style={{ height: '7px' }}>
                    <div style={{ height: '100%', width: `${pct}%`, background: met ? '#22a06b' : '#005956' }} />
                  </div>
                  <p className="font-medium" style={{ fontSize: '11px', marginTop: '5px', color: met ? '#22a06b' : '#b45309' }}>{met ? t.met : t.shortMsg(short)}</p>
                </div>
              )
            })}
            <div className="border-t border-slate-100" style={{ marginTop: '4px', paddingTop: '14px' }}>
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-slate-700">{t.totalLabel}</span>
                <span className="text-sm font-bold text-slate-800">{credit.total_earned} <span className="text-slate-400 font-medium">/ {credit.total_required}</span></span>
              </div>
              <p className="font-bold" style={{ fontSize: '13px', marginTop: '8px', color: '#005956' }}>{t.remainMsg(credit.remaining)}</p>
            </div>
            <p className="text-slate-400" style={{ fontSize: '11px', marginTop: '14px' }}>{t.note}</p>
          </div>
        </div>
      </div>
    )}

    {/* 대화 삭제 확인 */}
    {deleteTarget && (
      <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(15,23,42,.5)', padding: '16px' }} onClick={() => setDeleteTarget(null)}>
        <div className="bg-white rounded-2xl shadow-2xl w-full max-w-xs overflow-hidden" onClick={(e) => e.stopPropagation()}>
          <div style={{ padding: '20px 20px 16px' }}>
            <p className="font-bold text-slate-800" style={{ fontSize: '15px' }}>대화를 삭제할까요?</p>
            <p className="text-slate-500 truncate" style={{ fontSize: '13px', marginTop: '6px' }}>{deleteTarget.title}</p>
            <p className="text-slate-400" style={{ fontSize: '11px', marginTop: '8px' }}>삭제하면 되돌릴 수 없어요.</p>
          </div>
          <div className="flex border-t border-slate-100">
            <button
              onClick={() => setDeleteTarget(null)}
              className="flex-1 font-semibold text-slate-600 hover:bg-slate-50 transition"
              style={{ padding: '12px', fontSize: '13px' }}
            >
              취소
            </button>
            <button
              onClick={confirmDeleteSession}
              className="flex-1 font-semibold text-red-500 border-l border-slate-100 hover:bg-red-50 transition"
              style={{ padding: '12px', fontSize: '13px' }}
            >
              삭제
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  )
}
