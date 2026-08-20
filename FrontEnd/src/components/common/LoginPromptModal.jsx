import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../store/AuthContext'

const T = {
  ko: {
    title: '로그인이 필요해요',
    body: (f) => `${f}은(는) 학번·학과 정보를 기준으로 알려드리기 때문에 로그인이 필요합니다.`,
    open: '로그인 없이도 학사 규정, 학사일정, 학식, 캠퍼스 위치, 학과 안내, 신청서 서식은 그대로 이용하실 수 있어요.',
    login: '로그인하기',
    later: '나중에',
  },
  en: {
    title: 'Sign in required',
    body: (f) => `${f} is answered based on your student ID and department, so you need to sign in.`,
    open: 'Without signing in you can still use academic rules, the calendar, cafeteria menus, campus locations, department info, and form downloads.',
    login: 'Sign in',
    later: 'Not now',
  },
  zh: {
    title: '需要登录',
    body: (f) => `${f}需要根据您的学号和学院信息作答，因此需要登录。`,
    open: '未登录也可以使用学则、学事日程、食堂菜单、校园位置、学科介绍和申请书表格下载。',
    login: '去登录',
    later: '稍后',
  },
}

/**
 * 게스트가 로그인 필요한 기능을 눌렀을 때 뜨는 안내.
 * AuthContext의 loginPrompt 하나만 보고 App에서 렌더한다 — 화면마다 모달을 따로 두면
 * 문구와 동작이 갈린다.
 */
export default function LoginPromptModal({ lang = 'ko' }) {
  const { loginPrompt, closeLoginPrompt } = useAuth()
  const navigate = useNavigate()
  if (!loginPrompt) return null

  const t = T[lang] || T.ko

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.45)', padding: '20px' }}
      onClick={closeLoginPrompt}
    >
      <div
        className="bg-(--surface-card) border border-(--border) rounded-2xl shadow-xl w-full"
        style={{ maxWidth: '420px', padding: '26px' }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="flex items-center gap-2.5" style={{ marginBottom: '12px' }}>
          <span style={{ fontSize: '22px' }}>🔒</span>
          <p className="font-bold text-(--text)" style={{ fontSize: '18px' }}>{t.title}</p>
        </div>

        <p className="text-(--text)" style={{ fontSize: '14px', lineHeight: 1.6 }}>
          {t.body(loginPrompt.feature)}
        </p>
        <p className="text-(--text-muted)" style={{ marginTop: '10px', fontSize: '13px', lineHeight: 1.6 }}>
          {t.open}
        </p>

        <div className="flex gap-2.5" style={{ marginTop: '22px' }}>
          <button
            onClick={closeLoginPrompt}
            className="flex-1 border border-(--border) rounded-lg text-(--text-muted) hover:bg-(--brand-a5) transition"
            style={{ padding: '10px 0', fontSize: '14px' }}
          >
            {t.later}
          </button>
          <button
            onClick={() => { closeLoginPrompt(); navigate('/login') }}
            className="flex-1 rounded-lg bg-(--brand) text-white font-medium hover:opacity-90 transition"
            style={{ padding: '10px 0', fontSize: '14px' }}
          >
            {t.login}
          </button>
        </div>
      </div>
    </div>
  )
}
