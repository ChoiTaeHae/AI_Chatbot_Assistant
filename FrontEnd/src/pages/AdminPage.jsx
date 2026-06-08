import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import MascotAvatar from '../components/common/MascotAvatar'
import { useAuth } from '../store/AuthContext'
import { logout } from '../api/auth'
import { uploadDocument, fetchDocuments, deleteDocument } from '../api/admin'

const NAV_ITEMS = [
  { id: 'dashboard', label: '대시보드 요약', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
    </svg>
  )},
  { id: 'documents', label: '문서 관리 (RAG 지식고)', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
    </svg>
  )},
  { id: 'settings', label: '서비스 설정', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  )},
  { id: 'stats', label: '사용 통계', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 18L9 11.25l4.306 4.307a11.95 11.95 0 015.814-5.519l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941" />
    </svg>
  )},
  { id: 'security', label: '보안 및 권한', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
    </svg>
  )},
]

const MOCK_DOCUMENTS = [
  { id: 1, status: '활성', statusColor: 'green', category: '수강신청, 공통', title: '2026학년도 여름학기 수강편람 v2.1.pdf', version: 'v2.1', expiry: '~ 2026.08', chunks: 321, parsing: 'sLLM Advanced' },
  { id: 2, status: '활성', statusColor: 'green', category: '장학금, 컴퓨터공학', title: '2026 IT 혁신 장학 지원 기준 안내', version: 'v1.1', expiry: '~ 2026.12', chunks: 58, parsing: 'LlamaParse' },
  { id: 3, status: '검토 대기', statusColor: 'yellow', category: '복학, 학사행정', title: '2026 휴학/복학 절차 개정안(초안).docx', version: 'v1.0', expiry: '제한없음', chunks: 77, parsing: 'Simple Text' },
  { id: 4, status: '오류', statusColor: 'red', category: '학사규정', title: '2026 졸업요건 변경사항(최종).pdf', version: 'v2.2', expiry: '제한없음', chunks: '--', parsing: '파싱 실패' },
]

function StatusBadge({ status, color }) {
  const colors = {
    green: 'bg-green-100 text-green-700',
    yellow: 'bg-yellow-100 text-yellow-700',
    red: 'bg-red-100 text-red-700',
  }
  const dots = {
    green: 'bg-green-500',
    yellow: 'bg-yellow-500',
    red: 'bg-red-500',
  }
  return (
    <span className={`inline-flex items-center text-xs font-semibold ${colors[color]}`} style={{ gap: '6px', padding: '4px 10px', borderRadius: '6px' }}>
      <span className={`h-1.5 w-1.5 ${dots[color]}`} style={{ borderRadius: '3px' }} />
      {status}
    </span>
  )
}

export default function AdminPage() {
  const [activeNav, setActiveNav] = useState('documents')
  const [searchText, setSearchText] = useState('')
  const [docTitle, setDocTitle] = useState('')
  const [tags, setTags] = useState([])
  const [tagInput, setTagInput] = useState('')
  const [documents, setDocuments] = useState([])
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState(null) // { type: 'success'|'error', text }
  const [selectedFile, setSelectedFile] = useState(null)
  const [category, setCategory] = useState('')
  const fileInputRef = useRef(null)
  const { user, clearUser } = useAuth()
  const navigate = useNavigate()

  // 문서 목록 불러오기
  useEffect(() => {
    loadDocuments()
  }, [])

  async function loadDocuments() {
    try {
      const data = await fetchDocuments()
      setDocuments(data.documents || [])
    } catch (e) {
      console.error('문서 목록 조회 실패:', e)
    }
  }

  async function handleUpload() {
    if (!selectedFile) {
      setUploadMsg({ type: 'error', text: '파일을 선택해주세요.' })
      return
    }
    setUploading(true)
    setUploadMsg(null)
    try {
      const source = docTitle || selectedFile.name.replace(/\.[^.]+$/, '')
      const result = await uploadDocument(selectedFile, source)
      setUploadMsg({ type: 'success', text: result.message })
      setSelectedFile(null)
      setDocTitle('')
      setTags([])
      setCategory('')
      await loadDocuments()
    } catch (e) {
      setUploadMsg({ type: 'error', text: e.message })
    } finally {
      setUploading(false)
    }
  }

  async function handleDelete(source) {
    if (!confirm(`'${source}' 문서를 삭제하시겠습니까?`)) return
    try {
      await deleteDocument(source)
      await loadDocuments()
    } catch (e) {
      alert(e.message)
    }
  }

  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (file) {
      setSelectedFile(file)
      setDocTitle(file.name.replace(/\.[^.]+$/, ''))
      setUploadMsg(null)
    }
  }

  function handleTagKeyDown(e) {
    if (e.key === 'Enter' && tagInput.trim()) {
      e.preventDefault()
      setTags([...tags, tagInput.trim()])
      setTagInput('')
    }
  }

  async function handleLogout() {
    await logout()
    clearUser()
    navigate('/login')
  }

  const filtered = documents.filter(d =>
    d.source.includes(searchText) || (d.file_name || '').includes(searchText)
  )

  return (
    <div className="flex h-screen bg-[#f4f6f9] overflow-hidden">

      {/* 사이드바 */}
      <aside className="w-56 shrink-0 bg-white border-r border-slate-100 flex flex-col shadow-sm">
        {/* 로고 */}
        <div className="flex items-center border-b border-slate-100" style={{ gap: '10px', padding: '20px' }}>
          <MascotAvatar className="h-10 w-10 object-contain" />
          <span className="text-xl font-black text-[#005956]">SOL로몬</span>
        </div>

        {/* 네비게이션 */}
        <nav className="flex-1 flex flex-col" style={{ padding: '16px 12px', gap: '4px' }}>
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveNav(item.id)}
              className={`flex items-center rounded-xl text-sm font-medium transition text-left w-full ${
                activeNav === item.id
                  ? 'bg-[#005956]/10 text-[#005956] font-bold'
                  : 'text-slate-500 hover:bg-slate-50 hover:text-slate-700'
              }`}
              style={{ gap: '12px', padding: '10px 14px' }}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </nav>

        {/* 하단 마스코트 카드 */}
        <div className="m-3 p-3 rounded-2xl bg-[#f0f9f8] border border-[#005956]/10">
          <MascotAvatar className="h-14 w-14 object-contain mx-auto" />
          <p className="text-xs text-center text-slate-500 mt-2 font-medium">AI 어시스턴트가<br />문서를 분석하고 답변을 제공합니다.</p>
          <button
            onClick={() => navigate('/chat')}
            className="mt-2 w-full flex items-center justify-center gap-1.5 bg-white border border-[#005956]/20 text-[#005956] text-xs font-bold py-2 rounded-xl hover:bg-[#005956]/5 transition"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
            </svg>
            AI 어시스턴트 열기
          </button>
        </div>

        {/* 로그아웃 */}
        <button
          onClick={handleLogout}
          className="flex items-center text-sm font-medium text-slate-400 hover:text-red-500 hover:bg-red-50 transition border-t border-slate-100"
          style={{ gap: '8px', padding: '16px 24px' }}
        >
          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
          </svg>
          로그아웃
        </button>
      </aside>

      {/* 메인 영역 */}
      <div className="flex-1 flex flex-col min-w-0">

        {/* 헤더 */}
        <header className="shrink-0 bg-white border-b border-slate-100 flex items-center justify-between" style={{ padding: '16px 32px' }}>
          <h1 className="text-lg font-black text-[#05263d]">우송대 AI 캠퍼스 코치 - 문서 관리 포털</h1>
          <div className="flex items-center" style={{ gap: '16px' }}>
            <button className="text-slate-400 hover:text-slate-600 transition">
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
              </svg>
            </button>
            <div className="flex items-center" style={{ gap: '10px' }}>
              <MascotAvatar className="h-8 w-8 object-contain" />
              <div className="text-sm">
                <p className="font-bold text-slate-700">{user?.name || '관리자님'} · 교무처</p>
                <p className="text-xs text-slate-400">Admin</p>
              </div>
              <svg className="h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </div>
          </div>
        </header>

        {/* 본문 */}
        <main className="flex-1 overflow-y-auto flex gap-6" style={{ padding: '32px' }}>

          {/* 문서 목록 */}
          <div className="flex-1 bg-white rounded-2xl shadow-sm border border-slate-100 min-w-0 flex flex-col" style={{ padding: '32px' }}>
            <h2 className="text-base font-black text-[#05263d] mb-6">
              현재 RAG 지식 문서 목록
              <span className="ml-2 text-slate-400 font-normal text-sm">(Active Retrieval Documents)</span>
            </h2>

            {/* 필터 */}
            <div className="flex items-center flex-wrap" style={{ gap: '10px', marginBottom: '20px' }}>
              <select className="border border-slate-200 text-sm text-slate-600 outline-none focus:border-[#005956]" style={{ borderRadius: '8px', padding: '8px 14px' }}>
                <option>카테고리 전체</option>
              </select>
              <select className="border border-slate-200 text-sm text-slate-600 outline-none focus:border-[#005956]" style={{ borderRadius: '8px', padding: '8px 14px' }}>
                <option>상태 전체</option>
              </select>
              <select className="border border-slate-200 text-sm text-slate-600 outline-none focus:border-[#005956]" style={{ borderRadius: '8px', padding: '8px 14px' }}>
                <option>기간 전체</option>
              </select>
              <div className="flex items-center gap-2 border border-slate-200 ml-auto" style={{ borderRadius: '8px', padding: '8px 14px' }}>
                <svg className="h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
                </svg>
                <input
                  type="text"
                  placeholder="문서 제목 검색"
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                  className="text-sm outline-none text-slate-600 placeholder:text-slate-400 w-36"
                />
              </div>
            </div>

            {/* 테이블 */}
            <div className="flex-1 overflow-y-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100">
                  {['문서명 (source)', '파일명', '청크(Chunks)', '액션'].map(h => (
                    <th key={h} className="text-left text-xs font-bold text-slate-500 whitespace-nowrap" style={{ padding: '12px 16px' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={4} className="text-center text-slate-400 text-sm" style={{ padding: '32px' }}>
                      등록된 문서가 없습니다.
                    </td>
                  </tr>
                )}
                {filtered.map((doc, i) => (
                  <tr key={i} className="border-b border-slate-50 hover:bg-slate-50 transition">
                    <td className="font-medium text-slate-700" style={{ padding: '14px 16px' }}>{doc.source}</td>
                    <td className="text-slate-500 text-xs" style={{ padding: '14px 16px' }}>{doc.file_name || '-'}</td>
                    <td className="text-center text-slate-700 font-medium" style={{ padding: '14px 16px' }}>{doc.chunks}</td>
                    <td style={{ padding: '14px 16px' }}>
                      <button
                        onClick={() => handleDelete(doc.source)}
                        className="hover:text-red-500 transition text-slate-400"
                        title="삭제"
                      >
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                        </svg>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>

            <div className="flex items-center justify-between text-sm text-slate-400 border-t border-slate-100" style={{ marginTop: 'auto', paddingTop: '16px' }}>
              <span>총 {filtered.length}건의 문서</span>
              <div className="flex items-center gap-1">
                <button className="w-7 h-7 rounded-lg border border-slate-200 flex items-center justify-center hover:bg-slate-50">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
                <button className="w-7 h-7 rounded-lg bg-[#005956] text-white text-xs font-bold">1</button>
                <button className="w-7 h-7 rounded-lg border border-slate-200 flex items-center justify-center hover:bg-slate-50">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              </div>
            </div>
          </div>

          {/* 업로드 패널 */}
          <div className="w-72 shrink-0 bg-white rounded-2xl shadow-sm border border-slate-100 flex flex-col overflow-y-auto" style={{ padding: '20px', gap: '12px' }}>
            <h2 className="text-base font-black text-[#05263d]">새 문서 업로드 및 RAG 지식 추가</h2>

            {/* 드래그 앤 드롭 */}
            <input ref={fileInputRef} type="file" accept=".pdf,.docx,.pptx,.txt,.md" className="hidden" onChange={handleFileChange} />
            <div
              className="border-2 border-dashed border-slate-200 hover:border-[#005956]/40 transition cursor-pointer bg-slate-50 flex flex-col items-center"
              style={{ borderRadius: '10px', padding: '12px', gap: '6px' }}
              onClick={() => fileInputRef.current?.click()}
            >
              <svg className="h-8 w-8 text-slate-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z" />
              </svg>
              {selectedFile ? (
                <p className="text-sm font-medium text-[#005956] text-center">{selectedFile.name}</p>
              ) : (
                <p className="text-sm font-medium text-slate-400">파일 드래그 &amp; 드롭</p>
              )}
              <button
                type="button"
                className="bg-[#005956] text-white text-sm font-bold hover:bg-[#004a47] transition"
                style={{ borderRadius: '8px', padding: '8px 20px' }}
                onClick={(e) => { e.stopPropagation(); fileInputRef.current?.click() }}
              >
                파일 선택
              </button>
              <p className="text-xs text-slate-400">가능한 유형: PDF, DOCX, TXT, MD</p>
            </div>

            {/* 문서 제목 (source) */}
            <div className="flex flex-col" style={{ gap: '4px' }}>
              <label className="text-xs font-bold text-slate-600">문서명 (source)</label>
              <input
                type="text"
                placeholder="문서명을 입력하세요"
                value={docTitle}
                onChange={(e) => setDocTitle(e.target.value)}
                className="border border-slate-200 text-sm outline-none focus:border-[#005956] transition"
                style={{ borderRadius: '8px', padding: '6px 10px' }}
              />
            </div>

            {/* 키워드 태그 */}
            <div className="flex flex-col" style={{ gap: '4px' }}>
              <label className="text-xs font-bold text-slate-600">키워드 태그 (Enter로 추가)</label>
              <input
                type="text"
                placeholder="태그 입력 후 Enter"
                value={tagInput}
                onChange={(e) => setTagInput(e.target.value)}
                onKeyDown={handleTagKeyDown}
                className="border border-slate-200 text-sm outline-none focus:border-[#005956] transition"
                style={{ borderRadius: '8px', padding: '6px 10px' }}
              />
              <div className="flex flex-wrap" style={{ gap: '6px', marginTop: '4px' }}>
                {tags.map((tag) => (
                  <span key={tag} className="inline-flex items-center bg-slate-100 text-slate-600 text-xs font-medium" style={{ gap: '4px', padding: '4px 10px', borderRadius: '6px' }}>
                    {tag}
                    <button onClick={() => setTags(tags.filter(t => t !== tag))} className="text-slate-400 hover:text-red-400">×</button>
                  </span>
                ))}
              </div>
            </div>

            {/* 유효 기간 */}
            <div className="flex flex-col" style={{ gap: '4px' }}>
              <label className="text-xs font-bold text-slate-600">유효 기간 설정</label>
              <div className="flex items-center text-sm text-slate-500 border border-slate-200" style={{ gap: '8px', borderRadius: '8px', padding: '10px 14px' }}>
                <svg className="h-4 w-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 9v7.5" />
                </svg>
                2026.03.01 ~ 2026.08.31
              </div>
            </div>

            {/* 파싱 방식 */}
            <div className="flex flex-col" style={{ gap: '4px' }}>
              <label className="text-xs font-bold text-slate-600">파싱 방식 선택</label>
              <select
                className="border border-slate-200 text-sm outline-none focus:border-[#005956] transition text-slate-600"
                style={{ borderRadius: '8px', padding: '6px 10px' }}
              >
                <option>LlamaParse (표 추출 특화)</option>
                <option>sLLM Advanced</option>
                <option>Simple Text</option>
              </select>
            </div>

            {/* 업로드 결과 메시지 */}
            {uploadMsg && (
              <p className={`text-xs font-medium ${uploadMsg.type === 'success' ? 'text-[#005956]' : 'text-red-500'}`}>
                {uploadMsg.text}
              </p>
            )}

            {/* 버튼 */}
            <div className="flex mt-auto" style={{ gap: '8px' }}>
              <button
                onClick={handleUpload}
                disabled={uploading || !selectedFile}
                className="flex-1 flex items-center justify-center bg-[#005956] text-white text-sm font-black hover:bg-[#004a47] transition disabled:opacity-50 disabled:cursor-not-allowed"
                style={{ gap: '6px', borderRadius: '8px', padding: '12px 16px' }}
              >
                {uploading ? (
                  <>
                    <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    업로드 중...
                  </>
                ) : (
                  <>
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                    RAG 지식 추가
                  </>
                )}
              </button>
              <button
                onClick={() => { setSelectedFile(null); setDocTitle(''); setTags([]); setUploadMsg(null) }}
                className="border border-slate-200 text-sm font-bold text-slate-500 hover:bg-slate-50 transition"
                style={{ borderRadius: '8px', padding: '8px 12px' }}
              >
                취소
              </button>
            </div>
          </div>

        </main>
      </div>
    </div>
  )
}
