import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchMe, fetchDeptOptions, updateMe, changePassword } from '../api/me'
import { logout } from '../api/auth'
import { checkBackendHealth } from '../api/chat'
import { useAuth } from '../store/AuthContext'
import useIsMobile from '../hooks/useIsMobile'
import MascotAvatar from '../components/common/MascotAvatar'
import Toast from '../components/common/Toast'
import CourseSection from '../components/mypage/CourseSection'

/* 마이페이지 — 학생이 자기 정보를 고친다.
 *
 * 학년·전공계열을 편집 대상으로 둔 이유
 *   이 값들은 맞춤 장학금 매칭에 그대로 쓰이는데, 실제 성적 시스템 연동이 없어 서버가 학번
 *   기반 더미로 채운다. 학생이 고치지 못하면 매칭이 자기와 무관한 값으로 계산된다.
 *
 * 학번·이름은 신원이라 표시만 한다(서버도 수정을 받지 않는다).
 *
 * 세로로 쌓지 않고 탭으로 나눈 이유
 *   프로필·수강 이력·보안은 서로 목적이 다르고 같이 볼 일이 없는데, 한 페이지에 다 쌓으면
 *   수강 이력(39과목 이상)이 화면을 다 먹어 비밀번호 변경이 한참 아래로 밀린다.
 *   대신 신원·평점처럼 '어느 탭에서나 맥락이 되는 값'은 탭 위 프로필 카드에 항상 남긴다.
 *
 * 여백은 전역 `* { padding: 0 }` 리셋이 Tailwind 유틸을 덮어써서 인라인 style로 준다.
 */

const MAJOR_FIELDS = ['인문사회', '예술체육', '이공', '의학계열']
const GRADES = [1, 2, 3, 4]
const TABS = [
  { key: 'profile', label: '프로필' },
  { key: 'courses', label: '수강 이력' },
  { key: 'security', label: '보안' },
]

// 서버가 받아주는 최소 길이 (schemas/me.py PasswordChangeRequest.new_password)
const PW_MIN = 4

const ROLE_LABELS = { student: '학생', admin: '관리자' }

/* JWT payload에서 만료 시각만 꺼낸다.
   서명 검증은 서버 몫이고 여기선 '언제 풀리는지' 보여주려는 읽기라 디코딩만 한다.
   base64url이라 -/_ 를 되돌리고 padding을 채운다. 실패하면 null(칸을 숨기지 않고 '-'로 둔다). */
function decodeJwtExp(token) {
  try {
    const part = (token || '').split('.')[1]
    if (!part) return null
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/')
    const bytes = Uint8Array.from(atob(b64 + '==='.slice((b64.length + 3) % 4)),
      (c) => c.charCodeAt(0))
    const { exp } = JSON.parse(new TextDecoder().decode(bytes))
    return exp ? new Date(exp * 1000) : null
  } catch {
    return null
  }
}

// 남은 시간 대신 절대 시각을 쓴다 — '약 3시간 남음'은 다시 렌더될 때까지 낡은 값으로 남는다.
function formatExpiry(d) {
  if (!d) return '알 수 없음'
  if (d.getTime() <= Date.now()) return '만료됨'
  const time = d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
  const sameDay = d.toDateString() === new Date().toDateString()
  return sameDay ? `오늘 ${time}` : `${d.getMonth() + 1}/${d.getDate()} ${time}`
}

/* 비밀번호 강도 — 서버 조건이 '4자 이상'뿐이라 통과해도 매우 약한 값을 쓰게 된다.
   막지는 않고(정책은 서버 몫) 얼마나 약한지와 무엇을 더하면 나아지는지만 보여준다. */
const PW_LEVELS = [
  { label: '약함', color: 'var(--danger-text)', tip: '8자 이상으로 늘리면 훨씬 안전합니다.' },
  { label: '보통', color: 'var(--amber-text)', tip: '기호(!, @ 등)를 섞으면 더 안전합니다.' },
  { label: '강함', color: 'var(--brand)', tip: null },
]

function pwLevel(v) {
  let s = 0
  if (v.length >= 8) s++
  if (v.length >= 12) s++
  if (/[a-zA-Z]/.test(v) && /\d/.test(v)) s++
  if (/[^a-zA-Z0-9]/.test(v)) s++
  return s <= 1 ? 0 : s === 2 ? 1 : 2
}

/* 비밀번호 입력 한 칸 — 보이기 토글 포함.
   MyPage 안에서 정의하면 렌더마다 새 컴포넌트 타입이 되어 입력 도중 포커스가 날아간다. */
function PasswordField({ label, hint, value, onChange, autoComplete, invalid, inputCls, inputStyle, labelCls }) {
  const [show, setShow] = useState(false)
  return (
    <label className="flex flex-col" style={{ gap: '5px' }}>
      <span className={labelCls}>
        {label}{hint && <span className="font-normal text-(--text-faint)"> {hint}</span>}
      </span>
      <span style={{ position: 'relative', display: 'block' }}>
        {/* 오류 테두리는 인라인으로 준다 — inputCls의 border-(--border)/focus:border-(--brand)와
            같은 속성이라 클래스로 덧붙이면 CSS 순서에 따라 이기고 지는 게 갈린다. */}
        <input type={show ? 'text' : 'password'} autoComplete={autoComplete}
               value={value} onChange={(e) => onChange(e.target.value)}
               className={inputCls}
               style={{
                 ...inputStyle, paddingRight: '42px',
                 ...(invalid ? { borderColor: 'var(--danger-text)' } : null),
               }} />
        <button type="button" onClick={() => setShow((s) => !s)} tabIndex={-1}
                className="absolute text-(--text-faint) hover:text-(--text-muted) transition"
                aria-label={show ? '비밀번호 숨기기' : '비밀번호 보기'}
                style={{ right: '4px', top: '50%', transform: 'translateY(-50%)', padding: '8px' }}>
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" strokeWidth={1.7} aria-hidden="true">
            {show ? (
              <path strokeLinecap="round" strokeLinejoin="round"
                    d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243" />
            ) : (
              <>
                <path strokeLinecap="round" strokeLinejoin="round"
                      d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </>
            )}
          </svg>
        </button>
      </span>
    </label>
  )
}

export default function MyPage() {
  const navigate = useNavigate()
  const { user, saveUser, clearUser } = useAuth()
  const isMobile = useIsMobile()

  const [tab, setTab] = useState('profile')
  const [me, setMe] = useState(null)
  const [depts, setDepts] = useState([])
  const [form, setForm] = useState(null)          // 편집 중인 값
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [msg, setMsg] = useState(null)
  const [interestInput, setInterestInput] = useState('')
  // 방금 저장했는지 — 버튼 문구를 '저장됨'으로 잠깐 바꾼다.
  // dirty(변경 여부)만으로는 '아직 안 고침'과 '방금 저장함'이 같은 화면이라 저장이 됐는지 알기 어렵다.
  const [justSaved, setJustSaved] = useState(false)

  // 비밀번호 변경
  const [pw, setPw] = useState({ current: '', next: '', confirm: '' })
  const [pwSaving, setPwSaving] = useState(false)
  const [pwError, setPwError] = useState(null)
  const [pwMsg, setPwMsg] = useState(null)
  const [loggingOut, setLoggingOut] = useState(false)

  // 토큰은 로그인 때 한 번 정해지고 이 화면에서 바뀌지 않는다 → 마운트 시 한 번만 읽는다
  const tokenExp = useMemo(() => decodeJwtExp(sessionStorage.getItem('wsu_token')), [])

  const load = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const [profile, options] = await Promise.all([fetchMe(), fetchDeptOptions()])
      setMe(profile)
      setDepts(options)
      setForm({
        dept_id: profile.dept_id ?? '',
        grade_year: profile.grade_year ?? '',
        major_field: profile.major_field ?? '',
        interests: profile.interests ?? [],
      })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  /* 백엔드 재기동 감지 → 자동 새로고침.
     개발 중 서버를 다시 띄우면 이 화면은 옛 데이터를 그대로 들고 있어, 고친 값이 반영됐는지
     확인하려면 수동 새로고침을 해야 했다. 사이드바가 쓰는 것과 같은 방식으로 /health를
     가볍게 핑하고, 죽었다가 살아난 순간(down→up)에만 다시 불러온다.
     준비 상태면 15초, 대기 중이면 2초 간격 — 재기동을 빨리 잡되 평소엔 조용하다.
     탭이 백그라운드면 핑을 쉰다(브라우저가 타이머를 늦추기도 하고, 안 보는 화면을 갱신할
     이유도 없다). 돌아오면 visibilitychange에서 즉시 한 번 확인한다. */
  useEffect(() => {
    let up = true
    let timer
    let alive = true

    const ping = async () => {
      if (!alive) return
      if (document.visibilityState === 'visible') {
        const ok = await checkBackendHealth()
        if (ok && !up) {
          // 저장 안 한 편집이 있으면 덮어쓰지 않는다 — 서버 값으로 되돌려버리면
          // 사용자가 방금 고르던 학과·관심사가 소리 없이 사라진다.
          if (dirtyRef.current) {
            console.log('[MyPage] 백엔드 재기동 감지 — 편집 중이라 새로고침 보류')
          } else {
            console.log('[MyPage] 백엔드 재기동 감지 → 새로고침')
            load()
          }
        }
        up = ok
        timer = setTimeout(ping, ok ? 15000 : 2000)
        return
      }
      timer = setTimeout(ping, 5000)
    }
    timer = setTimeout(ping, 2000)

    const onVis = () => { if (document.visibilityState === 'visible') ping() }
    document.addEventListener('visibilitychange', onVis)
    return () => {
      alive = false
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [load])

  // 탭 바 높이를 재서 --sticky-offset으로 내려보낸다. 수강 이력의 학기 머리글도 sticky라,
  // 이 값이 없으면 탭 바 뒤로 파고들어 가린다. 패딩·글자 크기를 바꿔도 따라오도록 상수 대신 측정.
  const tabBarRef = useRef(null)
  const [stickyOffset, setStickyOffset] = useState(0)
  useEffect(() => {
    const el = tabBarRef.current
    if (!el) return
    setStickyOffset(el.offsetHeight)
    const ro = new ResizeObserver(() => setStickyOffset(el.offsetHeight))
    ro.observe(el)
    return () => ro.disconnect()
  }, [loading, isMobile])

  // 탭 바가 실제로 화면 위에 '붙었는지' — 붙었을 때만 아래 경계선을 그려, 카드가 그 밑으로
  // 지나간다는 게 보이게 한다. 스크롤 이벤트 대신 탭 바 바로 위의 1px 표식을 관찰한다
  // (스크롤마다 콜백이 도는 것을 피한다).
  const sentinelRef = useRef(null)
  const [stuck, setStuck] = useState(false)
  useEffect(() => {
    const el = sentinelRef.current
    if (!el) return
    const io = new IntersectionObserver(([entry]) => setStuck(!entry.isIntersecting))
    io.observe(el)
    return () => io.disconnect()
  }, [loading])

  // 학과 → 계열 자동 채움. 학과 목록에 계열이 실려 오므로 서버를 다시 부르지 않는다.
  function onDeptChange(value) {
    const id = value === '' ? '' : Number(value)
    const dept = depts.find((d) => d.id === id)
    setForm((f) => ({
      ...f,
      dept_id: id,
      major_field: dept?.major_field || f.major_field,
    }))
  }

  function addInterest() {
    const t = interestInput.trim()
    if (!t) return
    setForm((f) => (f.interests.includes(t) ? f : { ...f, interests: [...f.interests, t] }))
    setInterestInput('')
  }

  function removeInterest(t) {
    setForm((f) => ({ ...f, interests: f.interests.filter((x) => x !== t) }))
  }

  // 다시 고치기 시작하면 '저장됨' 표시를 즉시 거둔다(타이머를 기다리지 않는다)
  useEffect(() => {
    if (justSaved) setJustSaved(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form])

  // 감시 effect에서 읽으려고 ref에 담는다. deps에 dirty를 넣으면 값이 바뀔 때마다
  // 핑 타이머가 해제·재생성되어 주기가 흐트러진다.
  const dirtyRef = useRef(false)

  const dirty = useMemo(() => {
    if (!me || !form) return false
    return (
      (form.dept_id || null) !== (me.dept_id || null) ||
      (form.grade_year || null) !== (me.grade_year || null) ||
      (form.major_field || '') !== (me.major_field || '') ||
      JSON.stringify(form.interests) !== JSON.stringify(me.interests || [])
    )
  }, [me, form])

  useEffect(() => { dirtyRef.current = dirty }, [dirty])

  async function save() {
    setSaving(true); setError(null); setMsg(null)
    try {
      const payload = {
        dept_id: form.dept_id === '' ? null : Number(form.dept_id),
        grade_year: form.grade_year === '' ? null : Number(form.grade_year),
        major_field: form.major_field || null,
        interests: form.interests,
      }
      // null은 '바꾸지 않음'이라 서버가 무시한다 → 빈 값은 아예 빼서 보낸다
      Object.keys(payload).forEach((k) => payload[k] === null && delete payload[k])
      const updated = await updateMe(payload)
      setMe(updated)
      // 헤더에 쓰는 사용자 정보도 최신으로 (학과가 바뀌면 다른 화면에 반영)
      if (user) saveUser({ ...user, dept_name: updated.dept_name })
      setMsg('저장했습니다.')
      setTimeout(() => setMsg(null), 3000)
      setJustSaved(true)
      setTimeout(() => setJustSaved(false), 3000)
    } catch (e) {
      setError(e.message)
    } finally {
      setSaving(false)
    }
  }

  async function submitPassword() {
    setPwError(null); setPwMsg(null)
    if (!pw.current || !pw.next) { setPwError('현재 비밀번호와 새 비밀번호를 입력하세요.'); return }
    if (pw.next.length < PW_MIN) { setPwError(`새 비밀번호는 ${PW_MIN}자 이상이어야 합니다.`); return }
    if (pw.next !== pw.confirm) { setPwError('새 비밀번호가 서로 다릅니다.'); return }
    setPwSaving(true)
    try {
      await changePassword(pw.current, pw.next)
      setPw({ current: '', next: '', confirm: '' })
      setPwMsg('비밀번호를 변경했습니다.')
      setTimeout(() => setPwMsg(null), 4000)
    } catch (e) {
      setPwError(e.message)
    } finally {
      setPwSaving(false)
    }
  }

  // 서버 호출이 실패해도 로컬 세션은 반드시 지운다 — 여기서 멈추면 로그아웃을 눌렀는데
  // 로그인된 채로 남아 사용자가 '로그아웃됐다'고 오해한다. 서버 토큰 무효화는 실패해도
  // 어차피 만료 시각이 지나면 풀린다.
  async function handleLogout() {
    setLoggingOut(true)
    try {
      await logout()
    } catch {
      /* 무시 — 아래에서 로컬 세션을 지운다 */
    }
    clearUser()
    navigate('/login')
  }

  const inputCls = 'w-full border border-(--border) rounded-xl text-(--text) bg-(--surface-card) outline-none focus:border-(--brand) transition'
  const inputStyle = { padding: '11px 13px', fontSize: isMobile ? '16px' : '14px' }
  const labelCls = 'text-xs font-bold text-(--text-muted)'
  const cardCls = 'bg-(--surface-card) rounded-2xl shadow-sm border border-(--border)'
  const cardStyle = { padding: isMobile ? '18px 16px' : '24px 26px' }

  // 비밀번호 실시간 점검 — 예전에는 '변경' 버튼을 눌러야 길이·불일치를 알려줬다.
  // 빈 칸일 때는 아무 말도 하지 않는다(입력 시작 전부터 빨간 글씨를 띄우지 않기 위해).
  const pwTooShort = pw.next.length > 0 && pw.next.length < PW_MIN
  const pwLevelIdx = pw.next.length > 0 ? pwLevel(pw.next) : null
  const pwMismatch = pw.confirm.length > 0 && pw.next !== pw.confirm
  const pwMatched = pw.confirm.length > 0 && pw.next === pw.confirm && !pwTooShort
  // 학번은 로그인 아이디라 그대로 쓰면 사실상 잠금장치가 없는 것과 같다
  const pwIsStudentNo = pw.next.length > 0 && !!me && pw.next === me.student_no
  const pwSameAsCurrent = pw.next.length > 0 && pw.current.length > 0 && pw.next === pw.current

  // 탭 전환은 마운트를 유지한 채 보이기만 바꾼다 — 수강 이력을 다시 불러오지 않고,
  // 저장 전 편집값·필터 선택도 탭을 오가는 동안 그대로 남는다.
  const panelStyle = (key) => ({ display: tab === key ? 'block' : 'none' })

  return (
    <main className="bg-(--page)" style={{ minHeight: '100dvh' }}>
      {/* 헤더 */}
      <header className="bg-(--brand) flex items-center shadow-sm"
              style={{ gap: '12px', padding: isMobile ? '12px' : '14px 24px' }}>
        <button onClick={() => navigate('/chat')}
                className="text-white/90 hover:text-white shrink-0" aria-label="채팅으로 돌아가기">
          <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <MascotAvatar className={isMobile ? 'h-8 w-8' : 'h-10 w-10'} />
        <h1 className="font-black text-white" style={{ fontSize: isMobile ? '16px' : '18px' }}>마이페이지</h1>
      </header>

      {/* 900px — 760px일 땐 넓은 화면에서 양옆이 휑했고, 920px은 학과·관심목록 같은 한 줄짜리
          입력이 지나치게 길어졌다. 수강 이력이 [이수구분][과목명][학점][성적] 4열이라
          이 정도는 있어야 열 간격이 편하다. */}
      <div style={{
        maxWidth: '900px', margin: '0 auto',
        padding: isMobile ? '16px 12px 40px' : '28px 20px 60px',
        '--sticky-offset': `${stickyOffset}px`,
      }}>
        {/* 스켈레톤 — 프로필 카드·탭 바가 들어올 자리를 그대로 잡아 둔다 */}
        {loading && (
          <>
            <section className={cardCls} style={{ ...cardStyle, marginBottom: '4px' }}>
              <div className="flex items-center" style={{ gap: '14px' }}>
                <span className="skeleton shrink-0"
                      style={{ width: '52px', height: '52px', borderRadius: '9999px' }} />
                <div className="flex-1 min-w-0">
                  <span className="skeleton block" style={{ width: '96px', height: '20px' }} />
                  <span className="skeleton block" style={{ width: '210px', maxWidth: '100%', height: '13px', marginTop: '8px' }} />
                </div>
                <span className="skeleton shrink-0" style={{ width: '132px', height: '52px', borderRadius: '12px' }} />
              </div>
            </section>
            <div style={{ padding: '12px 0' }}>
              <span className="skeleton block" style={{ height: '43px', borderRadius: '12px' }} />
            </div>
            <section className={cardCls} style={cardStyle}>
              <span className="skeleton block" style={{ width: '80px', height: '15px' }} />
              <span className="skeleton block" style={{ height: '44px', borderRadius: '12px', marginTop: '20px' }} />
              <span className="skeleton block" style={{ height: '44px', borderRadius: '12px', marginTop: '14px' }} />
            </section>
          </>
        )}

        {!loading && me && (
          <>
            {/* 프로필 카드 — 신원과 평점은 어느 탭에서 작업하든 맥락이 되므로 탭 밖에 둔다 */}
            <section className={cardCls}
                     style={{ ...cardStyle, marginBottom: '4px' }}>
              <div className={`flex ${isMobile ? 'flex-col' : 'items-center'}`} style={{ gap: isMobile ? '16px' : '16px' }}>
                <div className="flex items-center min-w-0 flex-1" style={{ gap: '14px' }}>
                  <div className="rounded-full bg-(--brand-a10) text-(--brand) font-black flex items-center justify-center shrink-0"
                       style={{ width: '52px', height: '52px', fontSize: '20px' }} aria-hidden="true">
                    {me.name?.[0] ?? '?'}
                  </div>
                  <div className="min-w-0">
                    <p className="font-black text-(--text) truncate" style={{ fontSize: '20px' }}>{me.name}</p>
                    <p className="text-(--text-muted) truncate" style={{ fontSize: '13px', marginTop: '3px' }}>
                      {me.student_no}
                      {me.dept_name && <> · {me.dept_name}</>}
                      {me.grade_year && <> · {me.grade_year}학년</>}
                    </p>
                  </div>
                </div>

                {/* 평점평균 — 수강 이력에서 계산되는 읽기 전용 값이라 입력칸이 아니라 지표로 보여준다 */}
                <div className={`rounded-xl bg-(--surface-2) shrink-0 ${isMobile ? '' : 'text-right'}`}
                     style={{ padding: '10px 14px', minWidth: isMobile ? undefined : '132px' }}>
                  <p className="text-xs font-bold text-(--text-muted)">평점평균</p>
                  {me.gpa != null ? (
                    <p className="font-black text-(--text)" style={{ fontSize: '20px', marginTop: '2px' }}>
                      {me.gpa}<span className="font-normal text-(--text-faint)" style={{ fontSize: '13px' }}> / 4.5</span>
                    </p>
                  ) : (
                    <button onClick={() => setTab('courses')}
                            className="font-bold text-(--brand) hover:underline"
                            style={{ fontSize: '13px', marginTop: '4px' }}>
                      성적 엑셀 올리기 →
                    </button>
                  )}
                </div>
              </div>
            </section>

            {/* 탭 바가 화면 위에 붙었는지 알아내는 표식 — 눈에 보이지 않는다 */}
            <div ref={sentinelRef} style={{ height: '1px' }} aria-hidden="true" />

            {/* 탭 — 목록이 긴 수강 이력 탭에서도 항상 손에 닿도록 상단에 고정한다 */}
            <div ref={tabBarRef} role="tablist" aria-label="마이페이지 메뉴"
                 className="flex bg-(--page)"
                 style={{
                   position: 'sticky', top: 0, zIndex: 20, gap: '4px', padding: '12px 0',
                   borderBottom: `1px solid ${stuck ? 'var(--border)' : 'transparent'}`,
                   transition: 'border-color .2s',
                 }}>
              <div className="flex flex-1 bg-(--surface-2) border border-(--border) rounded-xl"
                   style={{ gap: '4px', padding: '4px' }}>
                {TABS.map((t) => {
                  const active = tab === t.key
                  return (
                    <button key={t.key} role="tab" aria-selected={active} type="button"
                            onClick={() => setTab(t.key)}
                            className={`flex-1 rounded-lg font-bold transition inline-flex items-center justify-center ${
                              active
                                ? 'bg-(--surface-card) text-(--brand) shadow-sm'
                                : 'text-(--text-muted) hover:text-(--text)'
                            }`}
                            style={{ gap: '5px', padding: '9px 6px', fontSize: '13px' }}>
                      {t.label}
                      {/* 저장 안 된 편집이 있으면 다른 탭에 있어도 보이게 */}
                      {t.key === 'profile' && dirty && (
                        <span className="rounded-full bg-(--brand) shrink-0"
                              style={{ width: '6px', height: '6px' }} aria-label="저장하지 않은 변경사항 있음" />
                      )}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* ── 프로필 탭 ── */}
            <div role="tabpanel" className="chat-view-enter" style={panelStyle('profile')}>
              <section className={cardCls} style={cardStyle}>
                <h2 className="font-black text-(--text)" style={{ fontSize: '15px' }}>학적 정보</h2>
                <p className="text-xs text-(--text-faint)" style={{ marginTop: '4px', marginBottom: '16px', lineHeight: 1.6 }}>
                  맞춤 장학금 추천에 사용됩니다. 실제와 다르면 추천 결과가 맞지 않으니 확인해 주세요.
                </p>

                <div className="flex flex-col" style={{ gap: '14px' }}>
                  {/* 학과는 '[단과대] 학과명'이라 길다 — 2열에 넣으면 잘리므로 한 줄을 다 준다 */}
                  <label className="flex flex-col" style={{ gap: '5px' }}>
                    <span className={labelCls}>학과</span>
                    <select className={inputCls} style={inputStyle}
                            value={form.dept_id} onChange={(e) => onDeptChange(e.target.value)}>
                      <option value="">선택 안 함</option>
                      {depts.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.college ? `[${d.college}] ` : ''}{d.name}
                        </option>
                      ))}
                    </select>
                  </label>

                  <div className="grid grid-cols-1 sm:grid-cols-2" style={{ gap: '14px' }}>
                    <label className="flex flex-col" style={{ gap: '5px' }}>
                      <span className={labelCls}>학년</span>
                      <select className={inputCls} style={inputStyle}
                              value={form.grade_year}
                              onChange={(e) => setForm({ ...form, grade_year: e.target.value })}>
                        <option value="">선택 안 함</option>
                        {GRADES.map((g) => <option key={g} value={g}>{g}학년</option>)}
                      </select>
                    </label>

                    <label className="flex flex-col" style={{ gap: '5px' }}>
                      <span className={labelCls}>
                        전공계열 <span className="font-normal text-(--text-faint)">(학과 선택 시 자동)</span>
                      </span>
                      <select className={inputCls} style={inputStyle}
                              value={form.major_field}
                              onChange={(e) => setForm({ ...form, major_field: e.target.value })}>
                        <option value="">선택 안 함</option>
                        {MAJOR_FIELDS.map((f) => <option key={f} value={f}>{f}</option>)}
                      </select>
                    </label>
                  </div>
                </div>

                {/* 관심 목록 */}
                <div style={{ marginTop: '18px' }}>
                  <span className={labelCls}>관심 목록</span>
                  <p className="text-xs text-(--text-faint)" style={{ marginTop: '3px' }}>
                    관심 있는 주제를 등록해 두면 추천에 참고됩니다.
                  </p>
                  <div className="flex" style={{ gap: '8px', marginTop: '10px' }}>
                    <input value={interestInput}
                           onChange={(e) => setInterestInput(e.target.value)}
                           onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addInterest() } }}
                           placeholder="예: 교환학생, 공모전"
                           className={inputCls} style={{ ...inputStyle, flex: 1 }} />
                    <button onClick={addInterest}
                            className="border border-(--brand-a20) rounded-xl text-sm font-bold text-(--brand) hover:bg-(--brand-a5) transition shrink-0"
                            style={{ padding: '0 18px' }}>추가</button>
                  </div>
                  <div className="flex flex-wrap" style={{ gap: '6px', marginTop: '10px' }}>
                    {form.interests.map((t) => (
                      <span key={t}
                            className="inline-flex items-center rounded-full bg-(--brand-a10) text-(--brand) font-bold"
                            style={{ gap: '6px', padding: '5px 8px 5px 12px', fontSize: '13px' }}>
                        {t}
                        <button onClick={() => removeInterest(t)}
                                className="text-(--brand) hover:text-red-500 transition"
                                aria-label={`${t} 삭제`} style={{ fontSize: '14px', lineHeight: 1 }}>✕</button>
                      </span>
                    ))}
                    {form.interests.length === 0 && (
                      <span className="text-xs text-(--text-faint)">등록된 관심사가 없습니다.</span>
                    )}
                  </div>
                </div>

                {error && <p className="text-xs font-bold text-red-500" style={{ marginTop: '14px' }}>{error}</p>}

                <div className="flex" style={{ gap: '8px', marginTop: '18px' }}>
                  {dirty && (
                    <button onClick={() => setForm({
                      dept_id: me.dept_id ?? '',
                      grade_year: me.grade_year ?? '',
                      major_field: me.major_field ?? '',
                      interests: me.interests ?? [],
                    })}
                            disabled={saving}
                            className="border border-(--border) rounded-xl font-bold text-(--text-muted) hover:bg-(--surface-2) transition disabled:opacity-50 shrink-0"
                            style={{ padding: '13px 18px', fontSize: '14px' }}>되돌리기</button>
                  )}
                  <button onClick={save} disabled={saving || !dirty}
                          className="flex-1 bg-(--brand) text-white rounded-xl font-black hover:bg-(--brand-hover) transition disabled:opacity-40 disabled:cursor-not-allowed"
                          style={{ padding: '13px', fontSize: '15px' }}>
                    {saving ? '저장 중…'
                      : justSaved ? '✓ 저장됨'
                      : dirty ? '변경사항 저장' : '변경된 내용 없음'}
                  </button>
                </div>

                <p className="text-xs text-(--text-faint)" style={{ marginTop: '14px', lineHeight: 1.6 }}>
                  이름과 학번은 변경할 수 없습니다. 잘못된 정보는 학사지원팀에 문의하세요.
                </p>
              </section>
            </div>

            {/* ── 수강 이력 탭 ── (평점평균·졸업 현황의 근거 데이터) */}
            <div role="tabpanel" className="chat-view-enter" style={panelStyle('courses')}>
              <CourseSection onGpaChange={(gpa) => setMe((m) => ({ ...m, gpa }))} />
            </div>

            {/* ── 보안 탭 ── */}
            <div role="tabpanel" className="chat-view-enter" style={panelStyle('security')}>
              {/* 2열 — 비밀번호는 짧은 입력이라 한 열이면 충분하고, 남는 폭은 로그인 상태가 채운다.
                  높이는 grid 기본값(stretch)으로 맞춘다. 두 카드 모두 flex column이라
                  남는 공간은 마지막 버튼 묶음의 marginTop:auto가 흡수해 버튼 줄이 나란히 선다. */}
              <div className="grid grid-cols-1 sm:grid-cols-2" style={{ gap: '16px' }}>
              <section className={cardCls} style={{ ...cardStyle, display: 'flex', flexDirection: 'column' }}>
                <h2 className="font-black text-(--text)" style={{ fontSize: '15px', marginBottom: '14px' }}>비밀번호 변경</h2>
                <div className="flex flex-col" style={{ gap: '14px' }}>
                  <PasswordField label="현재 비밀번호" autoComplete="current-password"
                                 value={pw.current} onChange={(v) => setPw({ ...pw, current: v })}
                                 inputCls={inputCls} inputStyle={inputStyle} labelCls={labelCls} />

                  <div>
                    <PasswordField label="새 비밀번호" hint={`(${PW_MIN}자 이상)`} autoComplete="new-password"
                                   value={pw.next} onChange={(v) => setPw({ ...pw, next: v })}
                                   invalid={pwTooShort}
                                   inputCls={inputCls} inputStyle={inputStyle} labelCls={labelCls} />

                    {pw.next.length > 0 && (
                      <>
                        {/* 강도 막대 — 채워진 칸 수가 곧 등급이다 */}
                        <div className="flex" style={{ gap: '4px', marginTop: '8px' }}>
                          {[0, 1, 2].map((i) => (
                            <span key={i} className="flex-1 rounded-full"
                                  style={{
                                    height: '4px',
                                    background: i <= pwLevelIdx ? PW_LEVELS[pwLevelIdx].color : 'var(--border)',
                                    transition: 'background .15s',
                                  }} />
                          ))}
                        </div>
                        <p className="text-xs" style={{ marginTop: '6px', lineHeight: 1.6 }}>
                          {pwTooShort ? (
                            <span className="font-bold text-red-500">
                              {PW_MIN}자 이상 입력해 주세요. (지금 {pw.next.length}자)
                            </span>
                          ) : (
                            <>
                              <b style={{ color: PW_LEVELS[pwLevelIdx].color }}>{PW_LEVELS[pwLevelIdx].label}</b>
                              {PW_LEVELS[pwLevelIdx].tip && (
                                <span className="text-(--text-faint)"> · {PW_LEVELS[pwLevelIdx].tip}</span>
                              )}
                            </>
                          )}
                        </p>
                      </>
                    )}

                    {pwIsStudentNo && (
                      <p className="text-xs font-bold text-red-500" style={{ marginTop: '6px' }}>
                        학번은 로그인 아이디입니다 — 비밀번호로 쓰지 마세요.
                      </p>
                    )}
                    {pwSameAsCurrent && (
                      <p className="text-xs font-bold text-red-500" style={{ marginTop: '6px' }}>
                        현재 비밀번호와 같습니다.
                      </p>
                    )}
                  </div>

                  <div>
                    <PasswordField label="새 비밀번호 확인" autoComplete="new-password"
                                   value={pw.confirm} onChange={(v) => setPw({ ...pw, confirm: v })}
                                   invalid={pwMismatch}
                                   inputCls={inputCls} inputStyle={inputStyle} labelCls={labelCls} />
                    {pwMismatch && (
                      <p className="text-xs font-bold text-red-500" style={{ marginTop: '6px' }}>
                        새 비밀번호가 서로 다릅니다.
                      </p>
                    )}
                    {pwMatched && (
                      <p className="text-xs font-bold text-(--brand)" style={{ marginTop: '6px' }}>
                        일치합니다.
                      </p>
                    )}
                  </div>
                </div>

                {/* marginTop:auto — 옆 카드가 더 길 때 남는 세로 공간을 여기서 흡수해
                    두 카드의 버튼이 같은 높이에 선다. 공간이 없으면 0이라 평소엔 무해하다. */}
                <div style={{ marginTop: 'auto' }}>
                  {pwError && <p className="text-xs font-bold text-red-500" style={{ marginTop: '12px' }}>{pwError}</p>}

                  <button onClick={submitPassword} disabled={pwSaving}
                          className="w-full border border-(--border) rounded-xl font-bold text-(--text-body) hover:bg-(--surface-2) transition disabled:opacity-50"
                          style={{ padding: '12px', fontSize: '14px', marginTop: '16px' }}>
                    {pwSaving ? '변경 중…' : '비밀번호 변경'}
                  </button>
                  <p className="text-xs text-(--text-faint)" style={{ marginTop: '10px', lineHeight: 1.6 }}>
                    변경해도 지금 로그인은 유지됩니다.
                  </p>
                </div>
              </section>

              {/* 로그인 상태 — 이 브라우저에 남아 있는 로그인이 어떤 상태인지 보여준다.
                  토큰이 sessionStorage에 있어 탭을 닫으면 사라진다는 걸 아무 데도 안 알려주고
                  있었다(로그인이 왜 풀렸는지 모르게 된다). */}
              <section className={cardCls} style={{ ...cardStyle, display: 'flex', flexDirection: 'column' }}>
                <h2 className="font-black text-(--text)" style={{ fontSize: '15px', marginBottom: '14px' }}>로그인 상태</h2>

                <dl className="flex flex-col" style={{ gap: '10px' }}>
                  {[
                    ['계정', me.name],
                    ['학번', me.student_no],
                    ['권한', ROLE_LABELS[user?.role] || user?.role || '학생'],
                    ['로그인 만료', formatExpiry(tokenExp)],
                  ].map(([k, v]) => (
                    <div key={k} className="flex items-baseline" style={{ gap: '12px' }}>
                      <dt className={`${labelCls} shrink-0`} style={{ width: '76px' }}>{k}</dt>
                      <dd className="text-(--text) truncate" style={{ fontSize: '14px' }}>{v}</dd>
                    </div>
                  ))}
                </dl>

                <p className="rounded-xl bg-(--surface-2) text-xs text-(--text-muted)"
                   style={{ padding: '11px 13px', marginTop: '16px', lineHeight: 1.7 }}>
                  로그인 정보를 <b className="text-(--text)">이 탭에만</b> 보관합니다 —
                  브라우저 탭을 닫으면 자동으로 로그아웃됩니다.
                </p>

                {/* 왼쪽 카드와 같은 이유로 버튼 묶음을 아래로 민다 (비밀번호 경고가 늘어나
                    왼쪽이 더 길어지는 경우도 있어 양쪽 다 걸어 둔다) */}
                <div style={{ marginTop: 'auto' }}>
                  <button onClick={handleLogout} disabled={loggingOut}
                          className="w-full border rounded-xl font-bold transition disabled:opacity-50"
                          style={{
                            padding: '12px', fontSize: '14px', marginTop: '12px',
                            borderColor: 'var(--danger-text)', color: 'var(--danger-text)',
                          }}>
                    {loggingOut ? '로그아웃 중…' : '이 기기에서 로그아웃'}
                  </button>
                  <p className="text-xs text-(--text-faint)" style={{ marginTop: '10px', lineHeight: 1.6 }}>
                    다른 기기에 남은 로그인은 여기서 끊을 수 없습니다 — 해당 기기에서 직접 로그아웃하세요.
                  </p>
                </div>
              </section>
              </div>
            </div>
          </>
        )}

        {!loading && !me && error && (
          <div className={cardCls} style={{ ...cardStyle, textAlign: 'center' }}>
            <p className="text-sm text-red-500">{error}</p>
            <button onClick={load}
                    className="border border-(--border) rounded-xl text-sm font-bold text-(--text-muted) hover:bg-(--surface-2) transition"
                    style={{ padding: '10px 20px', marginTop: '14px' }}>다시 시도</button>
          </div>
        )}
      </div>

      {/* 성공 알림 — 저장·비밀번호 변경 둘 다 여기로 모은다. 카드 안에 글자로 띄우면
          나타날 때 아래 내용이 밀려 화면이 흔들렸다. 오류는 각 입력 옆에 그대로 남긴다. */}
      <Toast message={msg || pwMsg} />
    </main>
  )
}
