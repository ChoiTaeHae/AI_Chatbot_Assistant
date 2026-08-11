import { useState, useEffect, useRef, Fragment } from 'react'
import { useNavigate } from 'react-router-dom'
import MascotAvatar from '../components/common/MascotAvatar'
import { useAuth } from '../store/AuthContext'
import { logout } from '../api/auth'
import { uploadDocument, fetchDocuments, deleteDocument, updateDocument, fetchChunks, updateChunk, pollUploadStatus, crawlDocument, fetchTopics, fetchTopicList, createTopic, updateTopic, deleteTopic } from '../api/admins/documents'
import { fetchDashboard, fetchStats, fetchChatStats } from '../api/admins/stats'
import { fetchSettings } from '../api/admins/settings'
import { fetchUsers, updateUserRole } from '../api/admins/security'
import { fetchFiles, uploadFile, deleteFile, downloadFile } from '../api/admins/files'
import { fetchChatSessions, fetchSessionMessages, upsertMessageFeedback } from '../api/admins/chats'
import ScheduleManager from '../components/admin/ScheduleManager'
import ScholarshipManager from '../components/admin/ScholarshipManager'
import DepartmentManager from '../components/admin/DepartmentManager'
import FaqManager from '../components/admin/FaqManager'
import ThemeToggle from '../components/common/ThemeToggle'

// 파일 관리 탭에서 숨길 topic — 장학금 파일은 '장학금 관리' 화면에서 전용 관리
const HIDDEN_FILE_TOPICS = ['scholarship', 'work_study']

const NAV_ITEMS = [
  { id: 'dashboard', label: '대시보드 요약', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
    </svg>
  )},
  { id: 'schedule', label: '학사일정', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0V11.25A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
    </svg>
  )},
  { id: 'documents', label: '문서 관리 (RAG)', icon: (
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
  { id: 'security', label: '보안 및 권한', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
    </svg>
  )},
  { id: 'files', label: '파일 관리', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
    </svg>
  )},
  { id: 'scholarships', label: '장학금 관리', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M4.26 10.147a60.436 60.436 0 00-.491 6.347A48.627 48.627 0 0112 20.904a48.627 48.627 0 018.232-4.41 60.46 60.46 0 00-.491-6.347m-15.482 0a50.57 50.57 0 00-2.658-.813A59.905 59.905 0 0112 3.493a59.902 59.902 0 0110.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.697 50.697 0 0112 13.489a50.702 50.702 0 017.74-3.342M6.75 15a.75.75 0 100-1.5.75.75 0 000 1.5zm0 0v-3.675A55.378 55.378 0 0112 8.443m-7.007 11.55A5.981 5.981 0 006.75 15.75v-1.5" />
    </svg>
  )},
  { id: 'chats', label: '채팅 내역', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
    </svg>
  )},
  { id: 'topics', label: 'Topic 관리', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M9.568 3H5.25A2.25 2.25 0 003 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 1.78.872 2.607.33a18.095 18.095 0 005.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 2.25 0 009.568 3z" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M6 6h.008v.008H6V6z" />
    </svg>
  )},
  { id: 'departments', label: '학과 관리', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 21v-8.25M15.75 21v-8.25M8.25 21v-8.25M3 9l9-6 9 6m-1.5 12V10.332A48.36 48.36 0 0012 9.75c-2.551 0-5.056.2-7.5.582V21M3 21h18M12 6.75h.008v.008H12V6.75z" />
    </svg>
  )},
  { id: 'faqs', label: 'FAQ 관리', icon: (
    <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm3.75 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm3.75 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
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
  const [documents, setDocuments] = useState([])
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState(null) // { type: 'success'|'error', text }
  const [selectedFile, setSelectedFile] = useState(null)
  const [topic, setTopic] = useState('')
  const [category, setCategory] = useState('')
  const [uploadMode, setUploadMode] = useState('document') // 'document' | 'crawl'
  const [crawlUrl, setCrawlUrl] = useState('')
  const [crawlSource, setCrawlSource] = useState('')
  const [crawlTopic, setCrawlTopic] = useState('')
  const [docDate, setDocDate] = useState('')
  const [crawlDocDate, setCrawlDocDate] = useState('')
  const [crawlContactName, setCrawlContactName] = useState('')
  const [crawlContactPhone, setCrawlContactPhone] = useState('')
  const [docUrl, setDocUrl] = useState('')
  const [docContactName, setDocContactName] = useState('')
  const [docContactPhone, setDocContactPhone] = useState('')
  // 문서 목록 인라인 수정 — 열린 행의 source, 폼 값, 저장 상태
  const [editingSource, setEditingSource] = useState(null)
  const [editForm, setEditForm] = useState({})
  const [editSaving, setEditSaving] = useState(false)
  const [editMsg, setEditMsg] = useState(null)
  // 청크 보기·수정 — 펼친 문서의 source, 불러온 청크 목록, 편집 중인 청크 번호
  const [chunkSource, setChunkSource] = useState(null)
  const [chunkList, setChunkList] = useState([])
  const [chunkLoading, setChunkLoading] = useState(false)
  const [editingChunk, setEditingChunk] = useState(null)
  const [chunkText, setChunkText] = useState('')
  const [chunkSaving, setChunkSaving] = useState(false)
  const [chunkMsg, setChunkMsg] = useState(null)
  const [crawling, setCrawling] = useState(false)
  const [crawlMsg, setCrawlMsg] = useState(null) // { type: 'success'|'error'|'info', text }
  const [topicFilter, setTopicFilter] = useState('all')
  const [topicLabels, setTopicLabels] = useState({})
  // 대시보드
  const [dashboard, setDashboard] = useState(null)
  // DB 현황 통계
  const [stats, setStats] = useState(null)
  // 채팅 사용 통계
  const [chatStats, setChatStats] = useState(null)
  // 서비스 설정
  const [settings, setSettings] = useState(null)
  // 보안/권한
  const [users, setUsers] = useState([])
  const [roleLoading, setRoleLoading] = useState(null) // 변경 중인 user id
  const [userPage, setUserPage] = useState(1)
  const USERS_PER_PAGE = 10

  // 파일 관리
  const [files, setFiles] = useState({})           // { graduation: [{name,size,topic,label}, ...], ... }
  const [fileLabels, setFileLabels] = useState({}) // { graduation: "졸업요건", ... }
  const [filesTopic, setFilesTopic] = useState('graduation')
  const [fileUploading, setFileUploading] = useState(false)
  const [fileMsg, setFileMsg] = useState(null)     // { type: 'success'|'error', text }
  // 채팅 내역
  const [chatSessions, setChatSessions] = useState([])
  const [chatSessionsTotal, setChatSessionsTotal] = useState(0)
  const [selectedSessionId, setSelectedSessionId] = useState(null)
  const [sessionMessages, setSessionMessages] = useState([])
  const [chatSearchText, setChatSearchText] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [msgLoading, setMsgLoading] = useState(false)
  const [openFeedbackId, setOpenFeedbackId] = useState(null)   // 현재 폼 열린 message id
  const [feedbackDraft, setFeedbackDraft] = useState({ is_helpful: null, rating: 0, comment: '' })
  const [savingFeedback, setSavingFeedback] = useState(false)
  const chatMessagesEndRef = useRef(null)

  // Topic 관리
  const [topicList, setTopicList] = useState([])
  const [topicMsg, setTopicMsg] = useState(null)
  const [editingTopic, setEditingTopic] = useState(null)  // {name, label, sentences, description}
  const [newTopic, setNewTopic] = useState({ name: '', label: '', handler_type: 'rag', sentences: '', description: '' })
  const [showNewTopicForm, setShowNewTopicForm] = useState(false)

  const filesInputRef = useRef(null)

  const fileInputRef = useRef(null)
  const profileRef = useRef(null)
  const [profileOpen, setProfileOpen] = useState(false)
  const { user, clearUser } = useAuth()
  const navigate = useNavigate()

  // 앱 초기 로드 시 토픽 목록 fetch
  useEffect(() => {
    fetchTopics().then(setTopicLabels).catch(console.error)
  }, [])

  async function loadTopicList() {
    try {
      const list = await fetchTopicList()
      setTopicList(list)
    } catch (e) { setTopicMsg({ type: 'error', text: e.message }) }
  }

  async function _refreshTopicCaches() {
    fetchTopics().then(labels => {
      setTopicLabels(labels)
      setFileLabels(labels)
      setFilesTopic(prev => labels[prev] ? prev : Object.keys(labels)[0] || '')
    }).catch(console.error)
  }

  async function handleCreateTopic() {
    try {
      const sentences = newTopic.sentences.split('\n').map(s => s.trim()).filter(Boolean)
      await createTopic({ ...newTopic, sentences })
      setTopicMsg({ type: 'success', text: `"${newTopic.label}" topic이 추가됐습니다.` })
      setNewTopic({ name: '', label: '', handler_type: 'rag', sentences: '', description: '' })
      setShowNewTopicForm(false)
      loadTopicList()
      _refreshTopicCaches()
    } catch (e) { setTopicMsg({ type: 'error', text: e.message }) }
  }

  async function handleUpdateTopic(name, data) {
    try {
      await updateTopic(name, data)
      setTopicMsg({ type: 'success', text: '수정됐습니다.' })
      setEditingTopic(null)
      loadTopicList()
      _refreshTopicCaches()
    } catch (e) { setTopicMsg({ type: 'error', text: e.message }) }
  }

  async function handleDeleteTopic(name) {
    if (!window.confirm(`"${name}" topic을 삭제하시겠습니까?`)) return
    try {
      await deleteTopic(name)
      setTopicMsg({ type: 'success', text: `"${name}" 삭제됐습니다.` })
      loadTopicList()
      _refreshTopicCaches()
    } catch (e) { setTopicMsg({ type: 'error', text: e.message }) }
  }

  // 탭 전환 시 해당 데이터 로드
  useEffect(() => {
    if (activeNav === 'documents') loadDocuments()
    if (activeNav === 'dashboard') { loadDashboard(); loadStats(); loadChatStats() }
    if (activeNav === 'settings') loadSettings()
    if (activeNav === 'security') loadUsers()
    if (activeNav === 'files') loadFiles()
    if (activeNav === 'chats') loadChatSessions()
    if (activeNav === 'topics') loadTopicList()
  }, [activeNav])

  // 프로필 드롭다운 바깥 클릭 시 닫기
  useEffect(() => {
    function handleClickOutside(e) {
      if (profileRef.current && !profileRef.current.contains(e.target)) {
        setProfileOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  async function loadDashboard() {
    try { setDashboard(await fetchDashboard()) } catch (e) { console.error(e) }
  }
  async function loadStats() {
    try { setStats(await fetchStats()) } catch (e) { console.error(e) }
  }
  async function loadChatStats() {
    try { setChatStats(await fetchChatStats()) } catch (e) { console.error(e) }
  }
  async function loadSettings() {
    try { setSettings(await fetchSettings()) } catch (e) { console.error(e) }
  }
  async function loadUsers() {
    try { const data = await fetchUsers(); setUsers(data.users || []) } catch (e) { console.error(e) }
  }

  async function loadFiles() {
    try {
      const data = await fetchFiles()
      setFiles(data.files || {})
      setFileLabels(data.labels || {})
    } catch (e) {
      console.error('파일 목록 조회 실패:', e)
    }
  }

  async function loadChatSessions(search = chatSearchText) {
    setChatLoading(true)
    try {
      const data = await fetchChatSessions({ search })
      setChatSessions(data.sessions || [])
      setChatSessionsTotal(data.total || 0)
    } catch (e) {
      console.error('채팅 세션 조회 실패:', e)
    } finally {
      setChatLoading(false)
    }
  }

  async function loadSessionMessages(sessionId) {
    setMsgLoading(true)
    setSelectedSessionId(sessionId)
    setSessionMessages([])
    setOpenFeedbackId(null)
    try {
      const data = await fetchSessionMessages(sessionId)
      setSessionMessages(data.messages || [])
      setTimeout(() => chatMessagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 50)
    } catch (e) {
      console.error('메시지 조회 실패:', e)
    } finally {
      setMsgLoading(false)
    }
  }

  async function handleFileUpload(e) {
    const file = e.target.files?.[0]
    if (!file) return
    setFileUploading(true)
    setFileMsg(null)
    try {
      const result = await uploadFile(file, filesTopic)
      setFileMsg({ type: 'success', text: result.message })
      await loadFiles()
    } catch (err) {
      setFileMsg({ type: 'error', text: err.message })
    } finally {
      setFileUploading(false)
      // input 초기화
      if (filesInputRef.current) filesInputRef.current.value = ''
    }
  }

  async function handleFileDelete(topic, filename) {
    if (!confirm(`'${filename}' 파일을 삭제하시겠습니까?`)) return
    try {
      await deleteFile(topic, filename)
      await loadFiles()
    } catch (err) {
      alert(err.message)
    }
  }

  async function handleFileDownload(topic, filename) {
    try {
      await downloadFile(topic, filename)
    } catch (err) {
      alert(err.message)
    }
  }

  async function handleRoleChange(userId, newRole) {
    setRoleLoading(userId)
    try {
      await updateUserRole(userId, newRole)
      await loadUsers()
    } catch (e) { alert(e.message) }
    finally { setRoleLoading(null) }
  }

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
    setUploadMsg({ type: 'info', text: '파일 업로드 중...' })
    try {
      const source = docTitle || selectedFile.name.replace(/\.[^.]+$/, '')
      const result = await uploadDocument(selectedFile, source, topic || null, docDate || null, docUrl || null, docContactName || null, docContactPhone || null)

      setUploadMsg({ type: 'info', text: 'RAG 처리 중입니다. 잠시 기다려주세요...' })

      // 백그라운드 처리 상태 폴링
      const final = await pollUploadStatus(result.job_id, (status) => {
        if (status.status === 'processing') {
          setUploadMsg({ type: 'info', text: '문서 파싱 및 임베딩 중...' })
        }
      })

      if (final.status === 'done') {
        setUploadMsg({ type: 'success', text: final.message })
        setSelectedFile(null)
        setDocTitle('')
        setTopic('')
        setDocUrl('')
        setDocContactName('')
        setDocContactPhone('')
        await loadDocuments()
      } else {
        setUploadMsg({ type: 'error', text: final.message || 'RAG 처리 중 오류가 발생했습니다.' })
      }
    } catch (e) {
      setUploadMsg({ type: 'error', text: e.message })
    } finally {
      setUploading(false)
    }
  }

  async function handleCrawl() {
    if (!crawlUrl) {
      setCrawlMsg({ type: 'error', text: 'URL을 입력해주세요.' })
      return
    }
    setCrawling(true)
    setCrawlMsg({ type: 'info', text: '크롤링 요청 중...' })
    try {
      const source = crawlSource || crawlUrl
      const result = await crawlDocument(crawlUrl, source, crawlTopic || null, crawlDocDate || null, crawlContactName || null, crawlContactPhone || null)

      setCrawlMsg({ type: 'info', text: '크롤링 및 RAG 처리 중입니다. 잠시 기다려주세요...' })

      const final = await pollUploadStatus(result.job_id, (status) => {
        if (status.status === 'processing') {
          setCrawlMsg({ type: 'info', text: '페이지 파싱 및 임베딩 중...' })
        }
      })

      if (final.status === 'done') {
        setCrawlMsg({ type: 'success', text: final.message })
        setCrawlUrl('')
        setCrawlSource('')
        setCrawlTopic('')
        setCrawlContactName('')
        setCrawlContactPhone('')
        await loadDocuments()
      } else {
        setCrawlMsg({ type: 'error', text: final.message || 'RAG 처리 중 오류가 발생했습니다.' })
      }
    } catch (e) {
      setCrawlMsg({ type: 'error', text: e.message })
    } finally {
      setCrawling(false)
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

  // 문서명을 누르면 그 행 아래에 수정 폼이 펼쳐진다. 같은 행을 다시 누르면 닫힌다.
  // 메타데이터만 수정하므로 본문·임베딩은 그대로다(재업로드와 달리 청크가 다시 만들어지지 않음).
  function toggleEditRow(doc) {
    if (editingSource === doc.source) { setEditingSource(null); return }
    setChunkSource(null)      // 한 행에 두 패널이 겹쳐 열리지 않게 한쪽만 연다
    setEditingSource(doc.source)
    setEditMsg(null)
    setEditForm({
      topic: doc.topic || '',
      doc_date: doc.doc_date || '',
      url: doc.url || '',
      contact_name: doc.contact_name || '',
      contact_phone: doc.contact_phone || '',
    })
  }

  async function handleUpdateDocument(source) {
    setEditSaving(true)
    setEditMsg(null)
    try {
      const result = await updateDocument(source, editForm)
      await loadDocuments()
      setEditMsg({ type: 'success', text: result.message })
    } catch (e) {
      setEditMsg({ type: 'error', text: e.message })
    } finally {
      setEditSaving(false)
    }
  }

  // 청크 아이콘을 누르면 그 행 아래에 실제 저장된 청크들이 펼쳐진다.
  async function toggleChunkRow(doc) {
    if (chunkSource === doc.source) { setChunkSource(null); return }
    setEditingSource(null)
    setChunkSource(doc.source)
    setChunkList([])
    setEditingChunk(null)
    setChunkMsg(null)
    setChunkLoading(true)
    try {
      const data = await fetchChunks(doc.source)
      setChunkList(data.chunks)
    } catch (e) {
      setChunkMsg({ type: 'error', text: e.message })
    } finally {
      setChunkLoading(false)
    }
  }

  function startEditChunk(chunk) {
    if (editingChunk === chunk.chunk_index) { setEditingChunk(null); return }
    setEditingChunk(chunk.chunk_index)
    setChunkText(chunk.text)
    setChunkMsg(null)
  }

  // 저장 후에는 목록을 다시 불러온다 — 서버가 앞뒤 공백을 다듬으므로,
  // 화면에 입력값을 그대로 남기면 '실제 저장된 내용'과 미묘하게 어긋난다.
  async function handleUpdateChunk(source, chunkIndex) {
    setChunkSaving(true)
    setChunkMsg(null)
    try {
      const result = await updateChunk(source, chunkIndex, chunkText)
      const data = await fetchChunks(source)
      setChunkList(data.chunks)
      setEditingChunk(null)
      setChunkMsg({ type: 'success', text: result.message })
    } catch (e) {
      setChunkMsg({ type: 'error', text: e.message })
    } finally {
      setChunkSaving(false)
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

  async function handleLogout() {
    await logout()
    clearUser()
    navigate('/login')
  }

  const filtered = documents.filter(d => {
    const matchesSearch = d.source.includes(searchText) || (d.file_name || '').includes(searchText)
    const matchesTopic =
      topicFilter === 'all' ? true :
      topicFilter === 'none' ? !d.topic :
      d.topic === topicFilter
    return matchesSearch && matchesTopic
  })

  return (
    /* minWidth를 루트에 걸면 태블릿(≈820px)에서 페이지 전체가 가로로 밀려 왼쪽 내비가
       화면 밖으로 잘려 나간다. 최소 폭은 아래 본문 래퍼로 옮기고, 가로 스크롤도 본문
       안에서만 일어나게 한다 → 내비·헤더는 항상 제자리. */
    <div className="flex h-screen bg-(--page) overflow-hidden">

      {/* 사이드바 */}
      <aside className="w-56 shrink-0 bg-(--surface-card) border-r border-(--border) flex flex-col shadow-sm">
        {/* 로고 */}
        <div className="flex items-center border-b border-(--border)" style={{ gap: '10px', padding: '20px' }}>
          <MascotAvatar className="h-10 w-10 object-contain" />
          <span className="text-xl font-black text-(--brand)">SOL로몬</span>
        </div>

        {/* 네비게이션 */}
        <nav className="flex-1 flex flex-col" style={{ padding: '16px 12px', gap: '4px' }}>
          {NAV_ITEMS.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveNav(item.id)}
              className={`flex items-center rounded-xl text-sm font-medium transition text-left w-full ${
                activeNav === item.id
                  ? 'bg-(--brand-a10) text-(--brand) font-bold'
                  : 'text-(--text-muted) hover:bg-(--surface-2) hover:text-(--text-body)'
              }`}
              style={{ gap: '12px', padding: '10px 14px' }}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </nav>

        {/* 하단 마스코트 카드 */}
        <div className="m-3 p-3 rounded-2xl bg-(--brand-tint) border border-(--brand-a10)">
          <MascotAvatar className="h-14 w-14 object-contain mx-auto" />
          <p className="text-xs text-center text-(--text-muted) mt-2 font-medium">AI 어시스턴트가<br />문서를 분석하고 답변을 제공합니다.</p>
          <button
            onClick={() => navigate('/chat')}
            className="mt-2 w-full flex items-center justify-center gap-1.5 bg-(--surface-card) border border-(--brand-a20) text-(--brand) text-xs font-bold py-2 rounded-xl hover:bg-(--brand-a5) transition"
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
          className="flex items-center text-sm font-medium text-(--text-faint) hover:text-red-500 hover:bg-red-50 transition border-t border-(--border)"
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
        <header className="shrink-0 bg-(--surface-card) border-b border-(--border) flex items-center justify-between relative z-50" style={{ padding: '16px 32px' }}>
          <h1 className="text-lg font-black text-(--text) truncate min-w-0">우송대 AI 캠퍼스 코치 - 문서 관리 포털</h1>
          <div className="flex items-center shrink-0" style={{ gap: '16px' }}>
            <ThemeToggle className="text-(--text-faint) hover:text-(--text-muted) transition" />
            {/* 프로필 드롭다운 */}
            <div className="relative" ref={profileRef}>
              <button
                onClick={() => setProfileOpen(v => !v)}
                className="flex items-center rounded-xl hover:bg-(--surface-2) transition"
                style={{ gap: '10px', padding: '6px 10px' }}
              >
                <MascotAvatar className="h-8 w-8 object-contain" />
                <div className="text-sm text-left">
                  <p className="font-bold text-(--text-body)">{user?.name || '관리자님'} · 교무처</p>
                  <p className="text-xs text-(--text-faint)">Admin</p>
                </div>
                <svg
                  className={`h-4 w-4 text-(--text-faint) transition-transform ${profileOpen ? 'rotate-180' : ''}`}
                  fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                >
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {/* 드롭다운 메뉴 */}
              {profileOpen && (
                <div className="absolute right-0 top-full mt-2 w-52 bg-(--surface-card) rounded-2xl shadow-lg border border-(--border) overflow-hidden z-50">
                  

                  {/* AI 어시스턴트로 이동 */}
                  <button
                    onClick={() => { setProfileOpen(false); navigate('/chat') }}
                    className="w-full flex items-center text-sm text-(--text-muted) hover:bg-(--brand-a5) hover:text-(--brand) transition"
                    style={{ gap: '10px', padding: '12px 16px' }}
                  >
                    <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
                    </svg>
                    AI 어시스턴트 열기
                  </button>

                  {/* 로그아웃 */}
                  <button
                    onClick={() => { setProfileOpen(false); handleLogout() }}
                    className="w-full flex items-center text-sm text-red-500 hover:bg-red-50 transition border-t border-(--border)"
                    style={{ gap: '10px', padding: '12px 16px' }}
                  >
                    <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15M12 9l-3 3m0 0l3 3m-3-3h12.75" />
                    </svg>
                    로그아웃
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* 본문 */}
        <main className="flex-1 overflow-auto" style={{ padding: '32px' }}>
          {/* 관리자 표·폼은 좁히면 되레 못 쓰게 되므로 최소 폭을 유지하고, 좁은 화면에서는
              이 안에서 가로로 밀어 본다(모바일 전면 대응은 하지 않음 — 데스크톱 전용 화면). */}
          <div className="flex gap-6" style={{ minWidth: '860px', height: '100%' }}>

          {/* 학사일정 */}
          {activeNav === 'schedule' && (
            <div className="flex-1 flex flex-col overflow-y-auto" style={{ gap: '20px' }}>
              <ScheduleManager />
            </div>
          )}

          {/* 장학금 관리 */}
          {activeNav === 'scholarships' && (
            <div className="flex-1 flex flex-col overflow-y-auto" style={{ gap: '20px' }}>
              <ScholarshipManager />
            </div>
          )}

          {/* 학과 관리 */}
          {activeNav === 'departments' && (
            <div className="flex-1 flex flex-col overflow-y-auto" style={{ gap: '20px' }}>
              <DepartmentManager />
            </div>
          )}

          {/* FAQ 관리 — 저장 시 서버가 메모리 인덱스를 자동 재적재한다 */}
          {activeNav === 'faqs' && (
            <div className="flex-1 flex flex-col min-h-0" style={{ gap: '20px' }}>
              <FaqManager />
            </div>
          )}

          {/* 대시보드 */}
          {activeNav === 'dashboard' && (
            <div className="flex-1 flex flex-col overflow-y-auto" style={{ gap: '20px' }}>

              {/* 요약 카드 행 */}
              <div className="grid grid-cols-4 gap-4">
                {[
                  { label: '전체 질문 수', value: chatStats ? chatStats.total_chats.toLocaleString() : '-', sub: '누적', color: 'var(--brand)' },
                  { label: '오늘 질문 수', value: chatStats ? chatStats.today_chats.toLocaleString() : '-', sub: '오늘', color: '#1d4ed8' },
                  { label: '활성 학생 (7일)', value: chatStats ? chatStats.active_students_7d.toLocaleString() : '-', sub: '최근 7일', color: '#7c3aed' },
                  { label: '전체 학생 수', value: stats ? stats.total_students.toLocaleString() : '-', sub: `관리자 ${stats?.total_admins ?? '-'}명 포함`, color: '#b45309' },
                ].map(({ label, value, sub, color }) => (
                  <div key={label} className="bg-(--surface-card) rounded-2xl shadow-sm border border-(--border)" style={{ padding: '20px 24px' }}>
                    <p className="text-xs font-semibold text-(--text-faint) truncate" style={{ marginBottom: '8px' }}>{label}</p>
                    <p className="text-3xl font-black truncate" style={{ color, marginBottom: '6px' }}>{value}</p>
                    <p className="text-xs text-(--text-faint) truncate">{sub}</p>
                  </div>
                ))}
              </div>

              {/* 그래프 행 */}
              <div className="grid grid-cols-2 gap-4">

                {/* 일별 질문 수 바 차트 */}
                <div className="bg-(--surface-card) rounded-2xl shadow-sm border border-(--border)" style={{ padding: '24px 28px' }}>
                  <p className="text-sm font-black text-(--text)" style={{ marginBottom: '20px' }}>최근 7일 질문 수</p>
                  {!chatStats ? (
                    <p className="text-(--text-faint) text-sm">불러오는 중...</p>
                  ) : (() => {
                    const data = chatStats.daily_counts
                    const max = Math.max(...data.map(d => d.count), 1)
                    return (
                      <div style={{ display: 'flex', flexWrap: 'nowrap', overflow: 'hidden', alignItems: 'flex-end', justifyContent: 'space-between', height: '130px', gap: '10px', padding: '0 4px' }}>
                        {data.map(d => (
                          <div key={d.date} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1, gap: '5px' }}>
                            <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-muted)', minHeight: '16px' }}>{d.count > 0 ? d.count : ''}</span>
                            <div style={{
                              width: '100%',
                              borderRadius: '5px 5px 0 0',
                              height: `${Math.max((d.count / max) * 88, d.count > 0 ? 6 : 2)}px`,
                              background: d.count > 0 ? 'var(--brand)' : 'var(--border)',
                              transition: 'height 0.3s',
                            }} />
                            <span style={{ fontSize: '11px', color: 'var(--text-faint)' }}>{d.date}</span>
                          </div>
                        ))}
                      </div>
                    )
                  })()}
                </div>

                {/* 주제별 분포 도넛 차트 */}
                <div className="bg-(--surface-card) rounded-2xl shadow-sm border border-(--border)" style={{ padding: '24px 28px' }}>
                  <p className="text-sm font-black text-(--text)" style={{ marginBottom: '20px' }}>주제별 질문 분포</p>
                  {!chatStats || chatStats.topic_counts.length === 0 ? (
                    <p className="text-(--text-faint) text-sm">아직 데이터가 없습니다</p>
                  ) : (() => {
                    const COLORS = ['var(--brand)','#1d4ed8','#7c3aed','#b45309','#0891b2','#16a34a','#dc2626','#9333ea']
                    const total = chatStats.topic_counts.reduce((s, t) => s + t.count, 0)
                    const r = 50, cx = 68, cy = 68, stroke = 20
                    const circumference = 2 * Math.PI * r
                    let offset = 0
                    const segments = chatStats.topic_counts.map((t, i) => {
                      const dash = (t.count / total) * circumference
                      const seg = { ...t, dash, offset, color: COLORS[i % COLORS.length] }
                      offset += dash
                      return seg
                    })
                    return (
                      <div style={{ display: 'flex', flexWrap: 'nowrap', overflow: 'hidden', alignItems: 'center', gap: '24px' }}>
                        <svg width="136" height="136" viewBox="0 0 136 136" style={{ flexShrink: 0 }}>
                          {segments.map((s, i) => (
                            <circle key={i} cx={cx} cy={cy} r={r} fill="none"
                              stroke={s.color} strokeWidth={stroke}
                              strokeDasharray={`${s.dash} ${circumference - s.dash}`}
                              strokeDashoffset={-s.offset + circumference * 0.25}
                              style={{ transform: 'rotate(-90deg)', transformOrigin: `${cx}px ${cy}px` }}
                            />
                          ))}
                          <text x={cx} y={cy - 7} textAnchor="middle" fontSize="17" fontWeight="900" fill="var(--text)">{total}</text>
                          <text x={cx} y={cy + 11} textAnchor="middle" fontSize="10" fill="var(--text-faint)">전체</text>
                        </svg>
                        <div style={{ display: 'flex', flexDirection: 'column', flex: 1, gap: '7px' }}>
                          {segments.map((s, i) => (
                            <div key={i} style={{ display: 'flex', flexWrap: 'nowrap', overflow: 'hidden', alignItems: 'center', justifyContent: 'space-between' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '7px' }}>
                                <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: s.color, flexShrink: 0 }} />
                                <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>{s.label}</span>
                              </div>
                              <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text)' }}>{s.count}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )
                  })()}
                </div>
              </div>

              {/* 시스템 상태 + DB 현황 */}
              <div className="grid grid-cols-2 gap-4">
                <div className="bg-(--surface-card) rounded-2xl shadow-sm border border-(--border)" style={{ padding: '24px 28px' }}>
                  <p className="text-sm font-black text-(--text)" style={{ marginBottom: '18px' }}>시스템 상태</p>
                  {!dashboard ? <p className="text-(--text-faint) text-sm">불러오는 중...</p> : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      {[
                        { label: 'RAG 문서', value: `${dashboard.total_documents}건 / ${dashboard.total_chunks}청크` },
                        { label: '모델 상태', value: dashboard.model_status === 'loaded' ? '✅ 로드됨' : '❌ 미로드' },
                        { label: 'DEV MODE', value: dashboard.dev_mode ? '⚠️ ON' : 'OFF' },
                        { label: '모델 경로', value: dashboard.model_path },
                      ].map(({ label, value }) => (
                        <div key={label} style={{ display: 'flex', flexWrap: 'nowrap', overflow: 'hidden', alignItems: 'flex-start', justifyContent: 'space-between', borderBottom: '1px solid var(--surface-2)', paddingBottom: '10px', gap: '12px' }}>
                          <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-faint)', flexShrink: 0, width: '80px' }}>{label}</span>
                          <span style={{ fontSize: '12px', color: 'var(--text-body)', fontFamily: 'monospace', textAlign: 'right', wordBreak: 'break-all' }}>{value}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="bg-(--surface-card) rounded-2xl shadow-sm border border-(--border)" style={{ padding: '24px 28px' }}>
                  <p className="text-sm font-black text-(--text)" style={{ marginBottom: '18px' }}>DB 현황</p>
                  {!stats ? <p className="text-(--text-faint) text-sm">불러오는 중...</p> : (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                      {[
                        { label: '전체 학생', value: stats.total_students, unit: '명' },
                        { label: '관리자', value: stats.total_admins, unit: '명' },
                        { label: '학과', value: stats.total_departments, unit: '개' },
                        { label: '과목', value: stats.total_courses, unit: '개' },
                      ].map(({ label, value, unit }) => (
                        <div key={label} style={{ background: 'var(--surface-2)', borderRadius: '12px', padding: '14px 16px' }}>
                          <p style={{ fontSize: '11px', color: 'var(--text-faint)', marginBottom: '4px' }}>{label}</p>
                          <p style={{ fontSize: '22px', fontWeight: 900, color: 'var(--text)' }}>
                            {value.toLocaleString()}
                            <span style={{ fontSize: '11px', fontWeight: 400, color: 'var(--text-faint)', marginLeft: '4px' }}>{unit}</span>
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

            </div>
          )}

          {/* 서비스 설정 */}
          {activeNav === 'settings' && (
            <div className="flex-1 bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) flex flex-col" style={{ padding: '32px', gap: '24px' }}>
              <h2 className="text-base font-black text-(--text)">서비스 설정</h2>
              {!settings ? (
                <p className="text-(--text-faint) text-sm">불러오는 중...</p>
              ) : (
                <div className="flex flex-col" style={{ gap: '8px' }}>
                  {[
                    { label: 'DEV MODE', value: settings.dev_mode ? 'true (LLM 스킵)' : 'false' },
                    /* 답변을 '지금 무엇이' 만드는지가 이 화면에서 가장 궁금한 값이라 맨 위에 둔다.
                       예전엔 모델 경로만 있어서 vertex로 돌 때도 로컬 GGUF 경로가 떴다. */
                    { label: '답변 생성', value: `${settings.llm_provider} · ${settings.llm_model}` },
                    { label: '로컬 LLM 경로', value: settings.model_path },
                    { label: 'DEVICE', value: settings.device },
                    { label: '임베딩 모델', value: settings.embedding_model },
                    { label: '임베딩 DEVICE', value: settings.embedding_device },
                    { label: 'Qdrant 컬렉션', value: settings.qdrant_collection },
                    { label: 'RAG Top-K', value: String(settings.rag_top_k) },
                  ].map(({ label, value }) => (
                    <div key={label} className="flex items-center justify-between border-b border-(--border) py-3">
                      <span className="text-sm font-bold text-(--text-muted) w-36 shrink-0">{label}</span>
                      <span className="text-sm text-(--text-body) font-mono bg-(--surface-2) rounded-lg px-3 py-1">{value}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* 보안 및 권한 */}
          {activeNav === 'security' && (
            <div className="flex-1 bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) flex flex-col" style={{ padding: '32px', gap: '20px' }}>
              <h2 className="text-base font-black text-(--text)">보안 및 권한 관리</h2>
              {users.length === 0 ? (
                <p className="text-(--text-faint) text-sm">불러오는 중...</p>
              ) : (() => {
                const totalPages = Math.ceil(users.length / USERS_PER_PAGE)
                const pageUsers = users.slice((userPage - 1) * USERS_PER_PAGE, userPage * USERS_PER_PAGE)
                return (
                  <>
                    <div className="overflow-y-auto">
                      <table className="w-full text-sm table-fixed">
                        <colgroup>
                          <col style={{ width: '15%' }} />
                          <col style={{ width: '20%' }} />
                          <col style={{ width: '25%' }} />
                          <col style={{ width: '20%' }} />
                          <col style={{ width: '20%' }} />
                        </colgroup>
                        <thead>
                          <tr className="border-b border-(--border)">
                            {['학번', '이름', '학과', '현재 권한', '권한 변경'].map(h => (
                              <th key={h} className="text-left text-xs font-bold text-(--text-muted) whitespace-nowrap" style={{ padding: '10px 12px' }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {pageUsers.map(u => (
                            <tr key={u.id} className="border-b border-(--border) hover:bg-(--surface-2) transition">
                              <td className="font-mono text-xs text-(--text-muted)" style={{ padding: '12px' }}>{u.student_no}</td>
                              <td className="font-medium text-(--text-body)" style={{ padding: '12px' }}>{u.name}</td>
                              <td className="text-(--text-muted) text-xs truncate" style={{ padding: '12px' }}>{u.department}</td>
                              <td style={{ padding: '12px' }}>
                                <span className={`inline-flex items-center text-xs font-semibold px-2 py-1 rounded-lg ${u.role === 'admin' ? 'bg-(--brand-a10) text-(--brand)' : 'bg-(--surface-2) text-(--text-muted)'}`}>
                                  {u.role === 'admin' ? '관리자' : '학생'}
                                </span>
                              </td>
                              <td style={{ padding: '12px' }}>
                                <button
                                  onClick={() => handleRoleChange(u.id, u.role === 'admin' ? 'student' : 'admin')}
                                  disabled={roleLoading === u.id}
                                  className="text-xs font-bold border border-(--border) hover:border-(--brand) hover:text-(--brand) text-(--text-muted) transition disabled:opacity-40 rounded-lg px-3 py-1"
                                >
                                  {roleLoading === u.id ? '변경 중...' : u.role === 'admin' ? '학생으로 변경' : '관리자로 변경'}
                                </button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    {/* 페이지네이션 */}
                    <div className="flex items-center justify-between text-sm text-(--text-faint) border-t border-(--border) overflow-hidden" style={{ paddingTop: '16px' }}>
                      <span className="shrink-0">총 {users.length}명</span>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setUserPage(p => p - 1)}
                          disabled={userPage === 1}
                          className="w-7 h-7 rounded-lg border border-(--border) flex items-center justify-center hover:bg-(--surface-2) disabled:opacity-30 disabled:cursor-not-allowed transition"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
                          </svg>
                        </button>
                        {Array.from({ length: totalPages }, (_, i) => i + 1)
                          .filter(p => p === 1 || p === totalPages || Math.abs(p - userPage) <= 1)
                          .reduce((acc, p, idx, arr) => {
                            if (idx > 0 && p - arr[idx - 1] > 1) acc.push('...')
                            acc.push(p)
                            return acc
                          }, [])
                          .map((p, idx) =>
                            p === '...' ? (
                              <span key={`dots-${idx}`} className="w-7 h-7 flex items-center justify-center text-xs text-(--text-faint)">…</span>
                            ) : (
                              <button
                                key={p}
                                onClick={() => setUserPage(p)}
                                className={`w-7 h-7 rounded-lg text-xs font-bold transition ${userPage === p ? 'bg-(--brand) text-white' : 'border border-(--border) hover:bg-(--surface-2)'}`}
                              >{p}</button>
                            )
                          )}
                        <button
                          onClick={() => setUserPage(p => p + 1)}
                          disabled={userPage === totalPages}
                          className="w-7 h-7 rounded-lg border border-(--border) flex items-center justify-center hover:bg-(--surface-2) disabled:opacity-30 disabled:cursor-not-allowed transition"
                        >
                          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                          </svg>
                        </button>
                      </div>
                    </div>
                  </>
                )
              })()}
            </div>
          )}

          {/* 문서 목록 */}
          {activeNav === 'documents' && (
          <div className="flex flex-col flex-1 min-h-0" style={{ gap: '16px' }}>

            {/* 업로드 패널 */}
            <div className="bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) shrink-0" style={{ padding: '20px 24px' }}>
              {/* 헤더 행: 제목 + 탭 */}
              <div className="flex items-center justify-between overflow-hidden" style={{ marginBottom: '14px' }}>
                <div>
                  <h2 className="text-base font-black text-(--text)">RAG 지식 추가</h2>
                  <p className="text-xs text-(--text-faint)" style={{ marginTop: '2px' }}>
                    {uploadMode === 'document' ? 'RAG 지식베이스에 추가 · PDF, DOCX, TXT, MD, HWPX, 이미지' : '웹페이지를 크롤링하여 RAG 지식베이스에 추가'}
                  </p>
                </div>
                <div className="flex border border-(--border) overflow-hidden text-sm font-bold" style={{ borderRadius: '8px' }}>
                  <button
                    onClick={() => setUploadMode('document')}
                    className={`transition ${uploadMode === 'document' ? 'bg-(--brand) text-white' : 'text-(--text-muted) hover:bg-(--surface-2)'}`}
                    style={{ padding: '7px 16px' }}
                  >
                    문서 업로드
                  </button>
                  <button
                    onClick={() => setUploadMode('crawl')}
                    className={`border-l border-(--border) transition ${uploadMode === 'crawl' ? 'bg-(--brand) text-white' : 'text-(--text-muted) hover:bg-(--surface-2)'}`}
                    style={{ padding: '7px 16px' }}
                  >
                    URL 크롤링
                  </button>
                </div>
              </div>

              {/* 문서 업로드 폼 */}
              {uploadMode === 'document' && (
              <div className="flex flex-col" style={{ gap: '8px' }}>
              {/* 1단: 파일 + 문서명 + 주제 + 기준날짜 */}
              <div className="flex items-end flex-wrap" style={{ gap: '12px' }}>

                {/* 파일 드롭 영역 */}
                {/* .hwp는 파서가 없어 업로드하면 백엔드가 400으로 거부한다(.hwpx만 처리 가능).
                    선택 단계에서 빼 두어야 '고를 수는 있는데 실패하는' 상황이 생기지 않는다. */}
                <input ref={fileInputRef} type="file" accept=".pdf,.docx,.pptx,.txt,.md,.hwpx,.png,.jpg,.jpeg,.webp,.bmp,.tiff,.tif" className="hidden" onChange={handleFileChange} />
                <div
                  className="border-2 border-dashed border-(--border) hover:border-(--brand-a40) transition cursor-pointer bg-(--surface-2) flex flex-col items-center justify-center shrink-0"
                  style={{ borderRadius: '10px', padding: '10px 16px', gap: '4px', width: '160px', height: '72px' }}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {selectedFile ? (
                    <>
                      <svg className="h-5 w-5 text-(--brand)" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
                      </svg>
                      <p className="text-xs font-medium text-(--brand) text-center" style={{ maxWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{selectedFile.name}</p>
                    </>
                  ) : (
                    <>
                      <svg className="h-6 w-6 text-(--text-faint)" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z" />
                      </svg>
                      <p className="text-xs text-(--text-faint)">클릭하여 파일 선택</p>
                    </>
                  )}
                </div>

                {/* 문서명 */}
                <div className="flex flex-col" style={{ gap: '4px', flex: 5, minWidth: 0 }}>
                  <label className="text-xs font-bold text-(--text-muted)">문서명 (source)</label>
                  <input
                    type="text"
                    placeholder="문서명을 입력하세요"
                    value={docTitle}
                    onChange={(e) => setDocTitle(e.target.value)}
                    className="border border-(--border) text-sm outline-none focus:border-(--brand) transition w-full"
                    style={{ borderRadius: '8px', padding: '8px 10px' }}
                  />
                </div>

                {/* 주제 분류 */}
                <div className="flex flex-col" style={{ gap: '4px', flex: 4, minWidth: 0 }}>
                  <label className="text-xs font-bold text-(--text-muted) whitespace-nowrap">주제 분류 (RAG 검색 필터)</label>
                  <select
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    className="border border-(--border) text-sm outline-none focus:border-(--brand) transition bg-(--surface-card) w-full"
                    style={{ borderRadius: '8px', padding: '8px 10px' }}
                  >
                    <option value="">선택 안 함 (전체 검색 대상)</option>
                    {Object.entries(topicLabels).map(([key, label]) => (
                      <option key={key} value={key}>{label}</option>
                    ))}
                  </select>
                </div>

                {/* 기준 날짜 */}
                <div className="flex flex-col" style={{ gap: '4px', flex: 3, minWidth: 0 }}>
                  <label className="text-xs font-bold text-(--text-muted) whitespace-nowrap">기준 날짜</label>
                  <input
                    type="date"
                    value={docDate}
                    onChange={(e) => setDocDate(e.target.value)}
                    className="border border-(--border) text-sm outline-none focus:border-(--brand) transition w-full"
                    style={{ borderRadius: '8px', padding: '8px 10px' }}
                  />
                </div>
              </div>

              {/* 2단: 출처URL + 담당부서 + 전화번호 + 버튼 */}
              <div className="flex items-end flex-wrap" style={{ gap: '12px' }}>

                {/* 출처 URL */}
                <div className="flex flex-col" style={{ gap: '4px', flex: 5, minWidth: 0 }}>
                  <label className="text-xs font-bold text-(--text-muted)">출처 URL</label>
                  <input
                    value={docUrl}
                    onChange={(e) => setDocUrl(e.target.value)}
                    placeholder="https://wsu.ac.kr/..."
                    className="border border-(--border) text-sm outline-none focus:border-(--brand) transition w-full"
                    style={{ borderRadius: '8px', padding: '8px 10px' }}
                  />
                </div>

                {/* 담당 부서 */}
                <div className="flex flex-col" style={{ gap: '4px', flex: 3, minWidth: 0 }}>
                  <label className="text-xs font-bold text-(--text-muted)">담당 부서</label>
                  <input
                    value={docContactName}
                    onChange={(e) => setDocContactName(e.target.value)}
                    placeholder="예: 학사팀"
                    className="border border-(--border) text-sm outline-none focus:border-(--brand) transition w-full"
                    style={{ borderRadius: '8px', padding: '8px 10px' }}
                  />
                </div>

                {/* 전화번호 */}
                <div className="flex flex-col" style={{ gap: '4px', flex: 3, minWidth: 0 }}>
                  <label className="text-xs font-bold text-(--text-muted)">전화번호</label>
                  <input
                    value={docContactPhone}
                    onChange={(e) => setDocContactPhone(e.target.value)}
                    placeholder="예: 042-630-9114"
                    className="border border-(--border) text-sm outline-none focus:border-(--brand) transition w-full"
                    style={{ borderRadius: '8px', padding: '8px 10px' }}
                  />
                </div>

                {/* 버튼 */}
                <div className="flex shrink-0" style={{ gap: '8px', alignItems: 'flex-end' }}>
                  <button
                    onClick={handleUpload}
                    disabled={uploading || !selectedFile}
                    className="flex items-center justify-center bg-(--brand) text-white text-sm font-black hover:bg-(--brand-hover) transition disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ gap: '6px', borderRadius: '8px', padding: '10px 18px' }}
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
                    onClick={() => { setSelectedFile(null); setDocTitle(''); setUploadMsg(null) }}
                    className="border border-(--border) text-sm font-bold text-(--text-muted) hover:bg-(--surface-2) transition"
                    style={{ borderRadius: '8px', padding: '10px 14px' }}
                  >
                    취소
                  </button>
                </div>

              </div>

              {/* 업로드 결과 메시지 */}
              {uploadMsg && (
                <p className={`text-xs font-medium truncate ${
                  uploadMsg.type === 'success' ? 'text-(--brand)' :
                  uploadMsg.type === 'info'    ? 'text-blue-500' :
                  'text-red-500'
                }`} title={uploadMsg.text}>
                  {uploadMsg.type === 'info' && '⏳ '}{uploadMsg.text}
                </p>
              )}
              </div>
              )}

              {/* URL 크롤링 폼 */}
              {uploadMode === 'crawl' && (
              <div className="flex flex-col" style={{ gap: '8px' }}>
              {/* 1단: URL + 문서명 + 주제 + 기준날짜 */}
              <div className="flex items-end flex-wrap" style={{ gap: '12px' }}>

                {/* URL 입력 */}
                <div className="flex flex-col" style={{ gap: '4px', flex: 5, minWidth: 0 }}>
                  <label className="text-xs font-bold text-(--text-muted)">크롤링 URL</label>
                  <input
                    type="url"
                    placeholder="https://..."
                    value={crawlUrl}
                    onChange={(e) => setCrawlUrl(e.target.value)}
                    className="border border-(--border) text-sm outline-none focus:border-(--brand) transition w-full"
                    style={{ borderRadius: '8px', padding: '8px 10px' }}
                  />
                </div>

                {/* 문서명 */}
                <div className="flex flex-col" style={{ gap: '4px', flex: 3, minWidth: 0 }}>
                  <label className="text-xs font-bold text-(--text-muted)">문서명 (source)</label>
                  <input
                    type="text"
                    placeholder="문서명을 입력하세요"
                    value={crawlSource}
                    onChange={(e) => setCrawlSource(e.target.value)}
                    className="border border-(--border) text-sm outline-none focus:border-(--brand) transition w-full"
                    style={{ borderRadius: '8px', padding: '8px 10px' }}
                  />
                </div>

                {/* 주제 분류 */}
                <div className="flex flex-col" style={{ gap: '4px', flex: 3, minWidth: 0 }}>
                  <label className="text-xs font-bold text-(--text-muted) whitespace-nowrap">주제 분류 (RAG 검색 필터)</label>
                  <select
                    value={crawlTopic}
                    onChange={(e) => setCrawlTopic(e.target.value)}
                    className="border border-(--border) text-sm outline-none focus:border-(--brand) transition bg-(--surface-card) w-full"
                    style={{ borderRadius: '8px', padding: '8px 10px' }}
                  >
                    <option value="">선택 안 함 (전체 검색 대상)</option>
                    {Object.entries(topicLabels).map(([key, label]) => (
                      <option key={key} value={key}>{label}</option>
                    ))}
                  </select>
                </div>

                {/* 기준 날짜 */}
                <div className="flex flex-col" style={{ gap: '4px', flex: 2, minWidth: 0 }}>
                  <label className="text-xs font-bold text-(--text-muted) whitespace-nowrap">기준 날짜</label>
                  <input
                    type="date"
                    value={crawlDocDate}
                    onChange={(e) => setCrawlDocDate(e.target.value)}
                    className="border border-(--border) text-sm outline-none focus:border-(--brand) transition w-full"
                    style={{ borderRadius: '8px', padding: '8px 10px' }}
                  />
                </div>
              </div>

              {/* 2단: 담당부서 + 전화번호 + 버튼 */}
              <div className="flex items-end flex-wrap" style={{ gap: '12px' }}>

                {/* 담당 부서 */}
                <div className="flex flex-col" style={{ gap: '4px', flex: 3, minWidth: 0 }}>
                  <label className="text-xs font-bold text-(--text-muted)">담당 부서</label>
                  <input
                    value={crawlContactName}
                    onChange={(e) => setCrawlContactName(e.target.value)}
                    placeholder="예: 학사팀"
                    className="border border-(--border) text-sm outline-none focus:border-(--brand) transition w-full"
                    style={{ borderRadius: '8px', padding: '8px 10px' }}
                  />
                </div>

                {/* 전화번호 */}
                <div className="flex flex-col" style={{ gap: '4px', flex: 3, minWidth: 0 }}>
                  <label className="text-xs font-bold text-(--text-muted)">전화번호</label>
                  <input
                    value={crawlContactPhone}
                    onChange={(e) => setCrawlContactPhone(e.target.value)}
                    placeholder="예: 042-630-9114"
                    className="border border-(--border) text-sm outline-none focus:border-(--brand) transition w-full"
                    style={{ borderRadius: '8px', padding: '8px 10px' }}
                  />
                </div>

                {/* 버튼 */}
                <div className="flex shrink-0" style={{ gap: '8px', alignItems: 'flex-end' }}>
                  <button
                    onClick={handleCrawl}
                    disabled={crawling || !crawlUrl}
                    className="flex items-center justify-center bg-(--brand) text-white text-sm font-black hover:bg-(--brand-hover) transition disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ gap: '6px', borderRadius: '8px', padding: '10px 18px' }}
                  >
                    {crawling ? (
                      <>
                        <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        크롤링 중...
                      </>
                    ) : (
                      <>
                        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244" />
                        </svg>
                        크롤링 시작
                      </>
                    )}
                  </button>
                  <button
                    onClick={() => { setCrawlUrl(''); setCrawlSource(''); setCrawlTopic(''); setCrawlMsg(null) }}
                    className="border border-(--border) text-sm font-bold text-(--text-muted) hover:bg-(--surface-2) transition"
                    style={{ borderRadius: '8px', padding: '10px 14px' }}
                  >
                    취소
                  </button>
                </div>

              </div>

              {/* 크롤링 결과 메시지 */}
              {crawlMsg && (
                <p className={`text-xs font-medium truncate ${
                  crawlMsg.type === 'success' ? 'text-(--brand)' :
                  crawlMsg.type === 'info'    ? 'text-blue-500' :
                  'text-red-500'
                }`} title={crawlMsg.text}>
                  {crawlMsg.type === 'info' && '⏳ '}{crawlMsg.text}
                </p>
              )}
              </div>
              )}
            </div>

            {/* 문서 목록 — 전체 너비 */}
            <div className="flex-1 bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) min-w-0 flex flex-col min-h-0" style={{ padding: '24px 32px' }}>
              <div className="flex items-center justify-between overflow-hidden" style={{ marginBottom: '12px' }}>
                <h2 className="text-base font-black text-(--text) truncate min-w-0">
                  현재 RAG 지식 문서 목록
                  <span className="ml-2 text-(--text-faint) font-normal text-sm">(Active Retrieval Documents)</span>
                </h2>
                <div className="flex items-center gap-2 border border-(--border)" style={{ borderRadius: '8px', padding: '6px 12px' }}>
                  <svg className="h-4 w-4 text-(--text-faint)" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
                  </svg>
                  <input
                    type="text"
                    placeholder="문서 검색"
                    value={searchText}
                    onChange={(e) => setSearchText(e.target.value)}
                    className="text-sm outline-none text-(--text-muted) placeholder:text-(--text-faint) w-40"
                  />
                </div>
              </div>

              {/* 카테고리 필터 드롭다운 */}
              <div className="flex items-center border-b border-(--border)" style={{ gap: '10px', marginBottom: '8px', paddingBottom: '10px' }}>
                <span className="text-xs font-bold text-(--text-muted) shrink-0">카테고리</span>
                <div className="relative" style={{ width: '220px' }}>
                  <select
                    value={topicFilter}
                    onChange={(e) => setTopicFilter(e.target.value)}
                    className="w-full border border-(--border) text-sm font-semibold text-(--text-muted) outline-none focus:border-(--brand) transition bg-(--surface-card) appearance-none"
                    style={{ borderRadius: '8px', padding: '7px 32px 7px 12px', maxHeight: '200px' }}
                  >
                    <option value="all">전체 ({documents.length})</option>
                    {Object.entries(topicLabels).map(([key, label]) => {
                      const count = documents.filter(d => d.topic === key).length
                      return <option key={key} value={key}>{label} ({count})</option>
                    })}
                    {documents.some(d => !d.topic) && (
                      <option value="none">미분류 ({documents.filter(d => !d.topic).length})</option>
                    )}
                  </select>
                  <svg className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 h-4 w-4 text-(--text-faint)" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto">
                <table className="w-full text-sm table-fixed">
                  <colgroup>
                    <col style={{ width: '30%' }} />
                    <col style={{ width: '20%' }} />
                    <col style={{ width: '14%' }} />
                    <col style={{ width: '14%' }} />
                    <col style={{ width: '12%' }} />
                    <col style={{ width: '10%' }} />
                  </colgroup>
                  <thead>
                    <tr className="border-b border-(--border)">
                      {['문서명 (source)', '파일명', '카테고리', '기준 날짜', '청크(Chunks)', '액션'].map(h => (
                        <th key={h} className={`text-xs font-bold text-(--text-muted) whitespace-nowrap ${h === '청크(Chunks)' ? 'text-right' : 'text-left'}`} style={{ padding: '10px 16px' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.length === 0 && (
                      <tr>
                        <td colSpan={5} className="text-center text-(--text-faint) text-sm" style={{ padding: '40px' }}>
                          등록된 문서가 없습니다.
                        </td>
                      </tr>
                    )}
                    {filtered.map((doc, i) => (
                      <Fragment key={doc.source}>
                      <tr className="border-b border-(--border) hover:bg-(--surface-2) transition">
                        <td className="font-medium text-(--text-body) truncate" style={{ padding: '13px 16px' }}>{doc.source}</td>
                        <td className="text-(--text-muted) text-xs truncate" style={{ padding: '13px 16px' }}>{doc.file_name || '-'}</td>
                        <td style={{ padding: '13px 16px', overflow: 'hidden' }}>
                          {doc.topic ? (
                            <span className="inline-flex items-center text-xs font-semibold px-2 py-0.5 rounded-md bg-(--brand-a8) text-(--brand) truncate max-w-full">
                              {topicLabels[doc.topic] || doc.topic}
                            </span>
                          ) : (
                            <span className="text-xs text-(--text-faint)">미분류</span>
                          )}
                        </td>
                        <td className="text-(--text-muted) text-xs" style={{ padding: '13px 16px' }}>{doc.doc_date || '-'}</td>
                        <td className="text-right text-(--text-body) font-medium" style={{ padding: '13px 16px' }}>{doc.chunks}</td>
                        <td style={{ padding: '13px 16px' }}>
                          <div className="flex items-center gap-2.5">
                            <button
                              onClick={() => toggleChunkRow(doc)}
                              className={`transition ${chunkSource === doc.source ? 'text-(--brand)' : 'text-(--text-faint) hover:text-(--brand)'}`}
                              title="청크 보기·수정"
                            >
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.008v.008H3.75V6.75zm0 5.25h.008v.008H3.75V12zm0 5.25h.008v.008H3.75v-.008z" />
                              </svg>
                            </button>
                            <button
                              onClick={() => toggleEditRow(doc)}
                              className={`transition ${editingSource === doc.source ? 'text-(--brand)' : 'text-(--text-faint) hover:text-(--brand)'}`}
                              title="수정"
                            >
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125" />
                              </svg>
                            </button>
                            <button
                              onClick={() => handleDelete(doc.source)}
                              className="hover:text-red-500 transition text-(--text-faint)"
                              title="삭제"
                            >
                              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                                <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                              </svg>
                            </button>
                          </div>
                        </td>
                      </tr>

                      {/* 청크 보기·수정 — 저장하면 그 청크 하나만 다시 임베딩된다 */}
                      {chunkSource === doc.source && (
                        <tr className="border-b border-(--border) bg-(--surface-2)">
                          <td colSpan={6} style={{ padding: '18px 20px' }}>
                            <div className="flex items-center justify-between gap-3" style={{ marginBottom: '14px' }}>
                              <span className="text-sm font-bold text-(--text) shrink-0">
                                청크 내용 · {doc.source}
                              </span>
                              <span className={`text-xs truncate min-w-0 ${
                                chunkMsg?.type === 'error' ? 'text-red-500'
                                : chunkMsg?.type === 'success' ? 'text-(--brand)'
                                : 'text-(--text-faint)'
                              }`}>
                                {chunkMsg?.text || '본문을 고쳐 저장하면 그 청크만 다시 임베딩돼요 (다른 청크는 그대로)'}
                              </span>
                            </div>

                            {chunkLoading ? (
                              <div className="text-xs text-(--text-faint)" style={{ padding: '12px 0' }}>불러오는 중...</div>
                            ) : (
                              <div className="flex flex-col gap-2">
                                {chunkList.map(chunk => (
                                  <div key={chunk.point_id} className="rounded-lg border border-(--border) bg-(--surface)" style={{ padding: '12px 14px' }}>
                                    <div className="flex items-center justify-between gap-3" style={{ marginBottom: '8px' }}>
                                      <div className="flex items-center gap-2 min-w-0">
                                        <span className="text-xs font-bold text-(--brand) shrink-0">#{chunk.chunk_index}</span>
                                        <span className="text-xs text-(--text-faint) shrink-0">{chunk.chars}자</span>
                                        {chunk.path && (
                                          <span className="text-xs text-(--text-muted) truncate">{chunk.path}</span>
                                        )}
                                      </div>
                                      <button
                                        onClick={() => startEditChunk(chunk)}
                                        className="text-xs font-semibold text-(--text-muted) hover:text-(--brand) transition shrink-0"
                                      >
                                        {editingChunk === chunk.chunk_index ? '닫기' : '수정'}
                                      </button>
                                    </div>

                                    {editingChunk === chunk.chunk_index ? (
                                      <>
                                        <textarea
                                          value={chunkText}
                                          onChange={e => setChunkText(e.target.value)}
                                          rows={14}
                                          spellCheck={false}
                                          className="w-full rounded-lg border border-(--border) bg-(--surface-2) text-xs text-(--text-body) leading-relaxed outline-none focus:border-(--brand) resize-y"
                                          style={{ padding: '10px 12px', fontFamily: 'ui-monospace, monospace' }}
                                        />
                                        <div className="flex items-center justify-between gap-3" style={{ marginTop: '10px' }}>
                                          <span className="text-xs text-(--text-faint)">
                                            {chunkText.length}자 (저장 전 {chunk.chars}자)
                                          </span>
                                          <div className="flex items-center gap-2 shrink-0">
                                            <button
                                              onClick={() => setEditingChunk(null)}
                                              className="rounded-lg border border-(--border) text-xs text-(--text-muted) hover:bg-(--surface-2) transition"
                                              style={{ padding: '6px 14px' }}
                                            >
                                              취소
                                            </button>
                                            <button
                                              onClick={() => handleUpdateChunk(doc.source, chunk.chunk_index)}
                                              disabled={chunkSaving}
                                              className="rounded-lg bg-(--brand) text-white text-xs font-bold hover:opacity-90 transition disabled:opacity-50"
                                              style={{ padding: '6px 16px' }}
                                            >
                                              {chunkSaving ? '재임베딩 중...' : '저장'}
                                            </button>
                                          </div>
                                        </div>
                                      </>
                                    ) : (
                                      <pre className="text-xs text-(--text-muted) whitespace-pre-wrap break-words leading-relaxed overflow-y-auto" style={{ maxHeight: '140px', fontFamily: 'ui-monospace, monospace' }}>
                                        {chunk.text}
                                      </pre>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}
                          </td>
                        </tr>
                      )}

                      {/* 인라인 수정 폼 — 메타데이터만 바꾸므로 본문·임베딩은 그대로 유지된다 */}
                      {editingSource === doc.source && (
                        <tr className="border-b border-(--border) bg-(--surface-2)">
                          <td colSpan={6} style={{ padding: '18px 20px' }}>
                            <div className="flex items-center justify-between" style={{ marginBottom: '14px' }}>
                              <span className="text-sm font-bold text-(--text)">문서 정보 수정</span>
                              <span className="text-xs text-(--text-faint)">
                                본문·임베딩은 그대로 두고 정보만 갱신해요 (청크 {doc.chunks}개)
                              </span>
                            </div>

                            <div className="grid grid-cols-3 gap-3" style={{ marginBottom: '12px' }}>
                              <label className="flex flex-col gap-1.5 min-w-0">
                                <span className="text-xs font-semibold text-(--text-muted)">주제 분류</span>
                                <select
                                  value={editForm.topic ?? ''}
                                  onChange={e => setEditForm({ ...editForm, topic: e.target.value })}
                                  className="w-full rounded-lg border border-(--border) bg-(--surface) text-sm text-(--text-body) outline-none focus:border-(--brand)"
                                  style={{ padding: '8px 10px' }}
                                >
                                  <option value="">미분류 (전체 검색 대상)</option>
                                  {Object.entries(topicLabels).map(([key, label]) => (
                                    <option key={key} value={key}>{label}</option>
                                  ))}
                                </select>
                              </label>
                              <label className="flex flex-col gap-1.5 min-w-0">
                                <span className="text-xs font-semibold text-(--text-muted)">기준 날짜</span>
                                <input
                                  type="date"
                                  value={editForm.doc_date ?? ''}
                                  onChange={e => setEditForm({ ...editForm, doc_date: e.target.value })}
                                  className="w-full rounded-lg border border-(--border) bg-(--surface) text-sm text-(--text-body) outline-none focus:border-(--brand)"
                                  style={{ padding: '8px 10px' }}
                                />
                              </label>
                              <label className="flex flex-col gap-1.5 min-w-0">
                                <span className="text-xs font-semibold text-(--text-muted)">담당 부서</span>
                                <input
                                  type="text"
                                  value={editForm.contact_name ?? ''}
                                  onChange={e => setEditForm({ ...editForm, contact_name: e.target.value })}
                                  placeholder="예: 학사팀"
                                  className="w-full rounded-lg border border-(--border) bg-(--surface) text-sm text-(--text-body) outline-none focus:border-(--brand)"
                                  style={{ padding: '8px 10px' }}
                                />
                              </label>
                            </div>

                            <div className="grid grid-cols-3 gap-3">
                              <label className="flex flex-col gap-1.5 col-span-2 min-w-0">
                                <span className="text-xs font-semibold text-(--text-muted)">출처 URL</span>
                                <input
                                  type="text"
                                  value={editForm.url ?? ''}
                                  onChange={e => setEditForm({ ...editForm, url: e.target.value })}
                                  placeholder="https://wsu.ac.kr/..."
                                  className="w-full rounded-lg border border-(--border) bg-(--surface) text-sm text-(--text-body) outline-none focus:border-(--brand)"
                                  style={{ padding: '8px 10px' }}
                                />
                              </label>
                              <label className="flex flex-col gap-1.5 min-w-0">
                                <span className="text-xs font-semibold text-(--text-muted)">전화번호</span>
                                <input
                                  type="text"
                                  value={editForm.contact_phone ?? ''}
                                  onChange={e => setEditForm({ ...editForm, contact_phone: e.target.value })}
                                  placeholder="예: 042-630-9114"
                                  className="w-full rounded-lg border border-(--border) bg-(--surface) text-sm text-(--text-body) outline-none focus:border-(--brand)"
                                  style={{ padding: '8px 10px' }}
                                />
                              </label>
                            </div>

                            <div className="flex items-center justify-between gap-3" style={{ marginTop: '14px' }}>
                              <span className={`text-xs min-w-0 truncate ${
                                editMsg?.type === 'error' ? 'text-red-500'
                                : editMsg?.type === 'success' ? 'text-(--brand)'
                                : 'text-transparent'
                              }`}>
                                {editMsg?.text || '.'}
                              </span>
                              <div className="flex items-center gap-2 shrink-0">
                                <button
                                  onClick={() => setEditingSource(null)}
                                  className="rounded-lg border border-(--border) text-sm text-(--text-muted) hover:bg-(--surface) transition"
                                  style={{ padding: '7px 16px' }}
                                >
                                  취소
                                </button>
                                <button
                                  onClick={() => handleUpdateDocument(doc.source)}
                                  disabled={editSaving}
                                  className="rounded-lg bg-(--brand) text-white text-sm font-bold hover:opacity-90 transition disabled:opacity-50"
                                  style={{ padding: '7px 18px' }}
                                >
                                  {editSaving ? '저장 중...' : '저장'}
                                </button>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="flex items-center justify-between text-sm text-(--text-faint) border-t border-(--border) overflow-hidden" style={{ paddingTop: '16px' }}>
                <span className="shrink-0">총 {filtered.length}건 · 청크 {documents.reduce((s, d) => s + (d.chunks || 0), 0).toLocaleString()}개</span>
              </div>
            </div>

          </div>
          )}

          {/* 파일 관리 */}
          {activeNav === 'files' && (
            <div className="flex-1 bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) flex flex-col" style={{ padding: '32px', gap: '20px' }}>
              {/* 헤더 */}
              <div className="flex items-center justify-between overflow-hidden">
                <div className="min-w-0">
                  <h2 className="text-base font-black text-(--text) truncate">파일 관리</h2>
                  <p className="text-xs text-(--text-faint) mt-0.5">학생에게 제공할 양식·자료를 topic별로 관리합니다</p>
                </div>
                <div className="flex items-center" style={{ gap: '8px' }}>
                  {fileUploading && (
                    <span className="text-xs text-blue-500 font-medium flex items-center gap-1">
                      <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                      </svg>
                      업로드 중...
                    </span>
                  )}
                  <input
                    ref={filesInputRef}
                    type="file"
                    accept=".pdf,.docx,.pptx,.xlsx,.hwp,.hwpx,.txt,.md,.jpg,.jpeg,.png"
                    className="hidden"
                    onChange={handleFileUpload}
                  />
                  <button
                    onClick={() => filesInputRef.current?.click()}
                    disabled={fileUploading}
                    className="flex items-center bg-(--brand) text-white text-sm font-bold hover:bg-(--brand-hover) transition disabled:opacity-50 rounded-xl"
                    style={{ gap: '6px', padding: '9px 16px' }}
                  >
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
                    </svg>
                    파일 추가
                  </button>
                </div>
              </div>

              {/* 알림 메시지 */}
              {fileMsg && (
                <div className={`text-xs font-medium px-4 py-2 rounded-xl ${fileMsg.type === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`}>
                  {fileMsg.text}
                </div>
              )}

              {/* Topic 드롭다운 */}
              <div className="flex items-center" style={{ gap: '10px' }}>
                <label className="text-xs font-bold text-(--text-muted) shrink-0">Topic</label>
                <div className="relative">
                  <select
                    value={filesTopic}
                    onChange={e => { setFilesTopic(e.target.value); setFileMsg(null) }}
                    className="text-sm font-semibold text-(--text) border border-(--border) rounded-xl bg-(--surface-card) outline-none focus:border-(--brand) appearance-none cursor-pointer"
                    style={{ padding: '7px 36px 7px 12px', minWidth: '160px' }}
                  >
                    {Object.entries(fileLabels).filter(([k]) => !HIDDEN_FILE_TOPICS.includes(k)).map(([topicKey, label]) => (
                      <option key={topicKey} value={topicKey}>
                        {label}{files[topicKey]?.length > 0 ? ` (${files[topicKey].length})` : ''}
                      </option>
                    ))}
                  </select>
                  <svg className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-(--text-faint)" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                  </svg>
                </div>
                {files[filesTopic]?.length > 0 && (
                  <span className="text-xs font-bold text-(--brand) bg-(--brand-a8) px-2 py-0.5 rounded-full">
                    {files[filesTopic].length}개
                  </span>
                )}
              </div>

              {/* 파일 목록 */}
              <div className="flex-1 overflow-y-auto">
                {(files[filesTopic] || []).length === 0 ? (
                  <div className="flex flex-col items-center justify-center text-(--text-faint)" style={{ padding: '60px 0', gap: '12px' }}>
                    <svg className="h-12 w-12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                    </svg>
                    <p className="text-sm font-medium">등록된 파일이 없습니다</p>
                    <p className="text-xs">오른쪽 상단 '파일 추가' 버튼으로 업로드하세요</p>
                  </div>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-(--border)">
                        {['파일명', '크기', '액션'].map((h, i) => (
                          <th key={h} className={`text-xs font-bold text-(--text-muted) ${i === 2 ? 'text-right' : 'text-left'}`} style={{ padding: '10px 12px' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(files[filesTopic] || []).map((f) => (
                        <tr key={f.name} className="border-b border-(--border) hover:bg-(--surface-2) transition group">
                          {/* width:100% → 파일명 칸이 남는 폭을 모두 차지 (크기·액션은 내용폭만) */}
                          <td className="font-medium text-(--text-body)" style={{ padding: '12px', width: '100%' }}>
                            <div className="flex items-center" style={{ gap: '8px' }}>
                              {/* 확장자 아이콘 */}
                              <span className={`shrink-0 text-xs font-bold px-1.5 py-0.5 rounded-md ${
                                f.name.endsWith('.pdf') ? 'bg-red-100 text-red-600' :
                                f.name.endsWith('.docx') || f.name.endsWith('.hwp') || f.name.endsWith('.hwpx') ? 'bg-blue-100 text-blue-600' :
                                f.name.endsWith('.xlsx') ? 'bg-green-100 text-green-600' :
                                f.name.endsWith('.pptx') ? 'bg-orange-100 text-orange-600' :
                                'bg-(--surface-2) text-(--text-muted)'
                              }`}>
                                {f.name.split('.').pop().toUpperCase()}
                              </span>
                              {/* 학사 파일명은 앞부분이 비슷해 짧게 자르면 구분이 안 된다(안산시 공고 3종 등).
                                  자르기는 유지하되 상한을 넓힘 — 실제 파일명 대부분이 이 안에 들어온다. */}
                              <span className="truncate max-w-2xl">{f.name}</span>
                            </div>
                          </td>
                          <td className="text-(--text-faint) text-xs whitespace-nowrap" style={{ padding: '12px' }}>
                            {f.size < 1024 ? `${f.size} B` :
                             f.size < 1024 * 1024 ? `${(f.size / 1024).toFixed(1)} KB` :
                             `${(f.size / 1024 / 1024).toFixed(1)} MB`}
                          </td>
                          <td style={{ padding: '12px' }}>
                            <div className="flex items-center justify-end" style={{ gap: '8px' }}>
                              {/* 다운로드 버튼 */}
                              <button
                                onClick={() => handleFileDownload(filesTopic, f.name)}
                                className="text-(--text-faint) hover:text-(--brand) transition"
                                title="다운로드"
                              >
                                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
                                </svg>
                              </button>
                              {/* 삭제 버튼 */}
                              <button
                                onClick={() => handleFileDelete(filesTopic, f.name)}
                                className="text-(--text-faint) hover:text-red-500 transition"
                                title="삭제"
                              >
                                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                                  <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                                </svg>
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              {/* 하단 정보 */}
              <div className="flex items-center justify-between text-xs text-(--text-faint) border-t border-(--border) pt-4">
                <span>
                  {fileLabels[filesTopic]} 탭 — 총 {(files[filesTopic] || []).length}개 파일
                </span>
                <span className="font-mono bg-(--surface-2) px-2 py-1 rounded-lg text-(--text-muted)">
                  documents/{filesTopic}/
                </span>
              </div>
            </div>
          )}
          

          {/* 채팅 내역 */}
          {activeNav === 'chats' && (() => {
            const INTENT_LABELS = {
              graduation: { label: '졸업요건', color: 'bg-teal-100 text-teal-700' },
              campus: { label: '캠퍼스', color: 'bg-blue-100 text-blue-700' },
              rag_general: { label: '일반학사', color: 'bg-purple-100 text-purple-700' },
              leave: { label: '휴학/복학', color: 'bg-yellow-100 text-yellow-700' },
              scholarship: { label: '장학금', color: 'bg-green-100 text-green-700' },
              dormitory: { label: '기숙사', color: 'bg-orange-100 text-orange-700' },
              course_registration: { label: '수강신청', color: 'bg-indigo-100 text-indigo-700' },
              general: { label: '일반', color: 'bg-(--surface-2) text-(--text-muted)' },
            }
            const selectedSession = chatSessions.find(s => s.id === selectedSessionId)
            const filteredSessions = chatSessions.filter(s =>
              !chatSearchText ||
              (s.student_name || '').includes(chatSearchText) ||
              (s.student_no || '').includes(chatSearchText) ||
              (s.first_message || '').includes(chatSearchText)
            )
            return (
              <div className="flex-1 flex gap-4 min-h-0">

                {/* 왼쪽: 세션 목록 */}
                <div className="w-72 shrink-0 bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) flex flex-col min-h-0">
                  <div className="shrink-0 border-b border-(--border)" style={{ padding: '20px 20px 14px' }}>
                    <div className="flex items-center justify-between" style={{ marginBottom: '10px' }}>
                      <h2 className="text-base font-black text-(--text)">채팅 내역</h2>
                      <span className="text-xs text-(--text-faint) font-medium">총 {chatSessionsTotal}건</span>
                    </div>
                    <div className="flex items-center gap-2 border border-(--border) rounded-xl" style={{ padding: '7px 12px' }}>
                      <svg className="h-3.5 w-3.5 text-(--text-faint) shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
                      </svg>
                      <input
                        type="text"
                        placeholder="이름·학번·내용 검색"
                        value={chatSearchText}
                        onChange={e => { setChatSearchText(e.target.value); loadChatSessions(e.target.value) }}
                        className="text-xs outline-none text-(--text-muted) placeholder:text-(--text-faint) w-full"
                      />
                    </div>
                  </div>

                  <div className="flex-1 overflow-y-auto" style={{ padding: '8px' }}>
                    {chatLoading ? (
                      <div className="flex items-center justify-center" style={{ padding: '40px 0' }}>
                        <svg className="h-5 w-5 animate-spin text-(--text-faint)" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                      </div>
                    ) : filteredSessions.length === 0 ? (
                      <p className="text-xs text-(--text-faint) text-center" style={{ padding: '40px 0' }}>채팅 내역이 없습니다</p>
                    ) : filteredSessions.map(s => {
                      const isSelected = selectedSessionId === s.id
                      const intent = INTENT_LABELS[s.intent] || INTENT_LABELS.general
                      const dateStr = s.last_message_at
                        ? new Date(s.last_message_at).toLocaleDateString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
                        : ''
                      return (
                        <button
                          key={s.id}
                          onClick={() => loadSessionMessages(s.id)}
                          className={`w-full text-left rounded-xl transition ${isSelected ? 'bg-(--brand-a8) border border-(--brand-a20)' : 'hover:bg-(--surface-2) border border-transparent'}`}
                          style={{ padding: '10px 12px', marginBottom: '2px' }}
                        >
                          <div className="flex items-center justify-between" style={{ marginBottom: '4px' }}>
                            <span className="text-sm font-bold text-(--text-body) truncate">{s.student_name || '알 수 없음'}</span>
                            <span className="text-xs text-(--text-faint) shrink-0 ml-2">{dateStr}</span>
                          </div>
                          <div className="flex items-center gap-1.5" style={{ marginBottom: '4px' }}>
                            <span className="text-xs text-(--text-faint) font-mono">{s.student_no}</span>
                            {s.intent && (
                              <span className={`text-xs font-semibold px-1.5 py-0.5 rounded-md ${intent.color}`}>
                                {intent.label}
                              </span>
                            )}
                            <span className="text-xs text-(--text-faint) ml-auto shrink-0">{s.message_count}건</span>
                          </div>
                          <p className="text-xs text-(--text-muted) truncate">{s.first_message || '(내용 없음)'}</p>
                        </button>
                      )
                    })}
                  </div>
                </div>

                {/* 오른쪽: 메시지 상세 */}
                <div className="flex-1 bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) flex flex-col min-h-0">
                  {!selectedSessionId ? (
                    <div className="flex-1 flex flex-col items-center justify-center text-(--text-faint)" style={{ gap: '12px' }}>
                      <svg className="h-14 w-14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
                      </svg>
                      <p className="text-sm font-medium">왼쪽에서 세션을 선택하세요</p>
                    </div>
                  ) : (
                    <>
                      <div className="shrink-0 border-b border-(--border) flex items-center justify-between" style={{ padding: '16px 24px' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-black text-(--text)">{selectedSession?.student_name || '-'}</span>
                            <span className="text-xs font-mono text-(--text-faint)">{selectedSession?.student_no}</span>
                            {selectedSession?.intent && (() => {
                              const intent = INTENT_LABELS[selectedSession.intent] || INTENT_LABELS.general
                              return <span className={`text-xs font-semibold px-2 py-0.5 rounded-md ${intent.color}`}>{intent.label}</span>
                            })()}
                          </div>
                          <span className="text-xs text-(--text-faint)">
                            {selectedSession?.started_at ? new Date(selectedSession.started_at).toLocaleString('ko-KR') : ''}
                            {' · '}{sessionMessages.length}개 메시지
                          </span>
                        </div>
                        <button
                          onClick={() => { setSelectedSessionId(null); setSessionMessages([]) }}
                          className="text-(--text-faint) hover:text-(--text-muted) transition"
                        >
                          <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
                            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </div>

                      <div className="flex-1 overflow-y-auto" style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                        {msgLoading ? (
                          <div className="flex items-center justify-center flex-1">
                            <svg className="h-6 w-6 animate-spin text-(--text-faint)" fill="none" viewBox="0 0 24 24">
                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                            </svg>
                          </div>
                        ) : sessionMessages.length === 0 ? (
                          <p className="text-sm text-(--text-faint) text-center" style={{ marginTop: '40px' }}>메시지가 없습니다</p>
                        ) : sessionMessages.map((msg, i) => {
                          const isUser = msg.role === 'user'
                          const timeStr = msg.created_at
                            ? new Date(msg.created_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
                            : ''
                          const intent = msg.intent ? (INTENT_LABELS[msg.intent] || INTENT_LABELS.general) : null
                          const fb = msg.feedback
                          const isFormOpen = openFeedbackId === msg.id

                          const openForm = () => {
                            setOpenFeedbackId(msg.id)
                            setFeedbackDraft({
                              is_helpful: fb ? fb.is_helpful : null,
                              rating: fb?.rating || 0,
                              comment: fb?.comment || '',
                            })
                          }

                          const saveFeedback = async () => {
                            if (feedbackDraft.is_helpful === null) return
                            setSavingFeedback(true)
                            try {
                              const saved = await upsertMessageFeedback(selectedSessionId, msg.id, feedbackDraft)
                              setSessionMessages(prev => prev.map(m =>
                                m.id === msg.id ? { ...m, feedback: saved } : m
                              ))
                              setOpenFeedbackId(null)
                            } catch (e) { alert(e.message) }
                            finally { setSavingFeedback(false) }
                          }

                          return (
                            <div key={msg.id || i} style={{ display: 'flex', flexDirection: 'column', alignItems: isUser ? 'flex-end' : 'flex-start', gap: '3px' }}>
                              <div className="flex items-center gap-1.5" style={{ flexDirection: isUser ? 'row-reverse' : 'row' }}>
                                <span className="text-xs font-bold text-(--text-faint)">{isUser ? '학생' : 'SOL로몬'}</span>
                                {!isUser && intent && (
                                  <span className={`text-xs font-semibold px-1.5 py-0.5 rounded-md ${intent.color}`}>{intent.label}</span>
                                )}
                                {!isUser && msg.source && (
                                  <span className="text-xs text-(--text-faint) font-mono truncate max-w-xs">{msg.source}</span>
                                )}
                              </div>
                              <div
                                className={`text-sm rounded-2xl whitespace-pre-wrap break-words ${
                                  isUser
                                    ? 'bg-(--brand) text-white rounded-tr-sm'
                                    : 'bg-(--surface-2) border border-(--border) text-(--text-body) rounded-tl-sm'
                                }`}
                                style={{ maxWidth: '72%', padding: '10px 14px', lineHeight: '1.6' }}
                              >
                                {msg.content}
                              </div>
                              <div className="flex items-center gap-1.5">
                                <span className="text-xs text-(--text-faint)">{timeStr}</span>
                                {/* 어시스턴트 메시지에만 피드백 버튼 표시 */}
                                {!isUser && (
                                  fb && !isFormOpen ? (
                                    /* 기존 피드백 뱃지 */
                                    <button
                                      onClick={openForm}
                                      className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-lg border border-(--border) hover:border-(--brand-a40) hover:text-(--brand) transition text-(--text-faint)"
                                    >
                                      {fb.is_helpful ? '👍' : '👎'}
                                      {fb.rating ? ` ${fb.rating}점` : ''}
                                      {fb.comment ? ' · 메모있음' : ''}
                                      <span className="ml-0.5">수정</span>
                                    </button>
                                  ) : !isFormOpen ? (
                                    /* 피드백 없을 때 작성 버튼 */
                                    <button
                                      onClick={openForm}
                                      className="text-xs text-(--text-faint) hover:text-(--brand) transition"
                                    >
                                      + 피드백
                                    </button>
                                  ) : null
                                )}
                              </div>

                              {/* 인라인 피드백 폼 */}
                              {!isUser && isFormOpen && (
                                <div className="bg-(--surface-card) border border-(--border) rounded-2xl shadow-sm" style={{ maxWidth: '72%', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                                  {/* 👍 / 👎 */}
                                  <div className="flex items-center gap-2">
                                    <span className="text-xs font-bold text-(--text-muted) w-14 shrink-0">평가</span>
                                    <button
                                      onClick={() => setFeedbackDraft(d => ({ ...d, is_helpful: true }))}
                                      className={`text-lg px-3 py-1 rounded-xl border transition ${feedbackDraft.is_helpful === true ? 'border-(--brand) bg-(--brand-a8)' : 'border-(--border) hover:border-(--border-strong)'}`}
                                    >👍</button>
                                    <button
                                      onClick={() => setFeedbackDraft(d => ({ ...d, is_helpful: false }))}
                                      className={`text-lg px-3 py-1 rounded-xl border transition ${feedbackDraft.is_helpful === false ? 'border-red-400 bg-red-50' : 'border-(--border) hover:border-(--border-strong)'}`}
                                    >👎</button>
                                  </div>

                                  {/* 별점 */}
                                  <div className="flex items-center gap-2">
                                    <span className="text-xs font-bold text-(--text-muted) w-14 shrink-0">별점</span>
                                    <div className="flex gap-1">
                                      {[1,2,3,4,5].map(n => (
                                        <button
                                          key={n}
                                          onClick={() => setFeedbackDraft(d => ({ ...d, rating: d.rating === n ? 0 : n }))}
                                          className={`text-lg transition ${n <= feedbackDraft.rating ? 'text-yellow-400' : 'text-(--text-faint) hover:text-yellow-300'}`}
                                        >★</button>
                                      ))}
                                    </div>
                                  </div>

                                  {/* 메모 */}
                                  <div className="flex items-start gap-2">
                                    <span className="text-xs font-bold text-(--text-muted) w-14 shrink-0 pt-1.5">메모</span>
                                    <textarea
                                      value={feedbackDraft.comment}
                                      onChange={e => setFeedbackDraft(d => ({ ...d, comment: e.target.value }))}
                                      placeholder="관리자 메모 (선택)"
                                      rows={2}
                                      className="flex-1 text-xs border border-(--border) rounded-xl outline-none focus:border-(--brand) resize-none"
                                      style={{ padding: '7px 10px' }}
                                    />
                                  </div>

                                  {/* 버튼 */}
                                  <div className="flex items-center gap-2 justify-end">
                                    <button
                                      onClick={() => setOpenFeedbackId(null)}
                                      className="text-(--text-faint) hover:text-(--text-muted) transition border border-(--border) hover:bg-(--surface-2) rounded-lg"
                                      style={{ fontSize: '11px', padding: '6px 14px' }}
                                    >취소</button>
                                    <button
                                      onClick={saveFeedback}
                                      disabled={feedbackDraft.is_helpful === null || savingFeedback}
                                      className="font-bold bg-(--brand) text-white rounded-lg hover:bg-(--brand-hover) transition disabled:opacity-40"
                                      style={{ fontSize: '11px', padding: '6px 14px' }}
                                    >{savingFeedback ? '저장 중...' : '저장'}</button>
                                  </div>
                                </div>
                              )}
                            </div>
                          )
                        })}
                        <div ref={chatMessagesEndRef} />
                      </div>
                    </>
                  )}
                </div>

              </div>
            )
          })()}

          {/* ── Topic 관리 ── */}
          {activeNav === 'topics' && (
            <div className="flex-1 bg-(--surface-card) rounded-2xl shadow-sm border border-(--border) flex flex-col min-h-0" style={{ padding: '24px' }}>
              {/* 헤더 */}
              <div className="flex items-center justify-between shrink-0" style={{ marginBottom: '16px' }}>
                <div>
                  <h2 className="text-base font-black text-(--text)">Topic 관리</h2>
                  <p className="text-xs text-(--text-faint)" style={{ marginTop: '2px' }}>질문 분류 topic을 추가·수정·삭제합니다. 시스템 topic은 삭제할 수 없습니다.</p>
                </div>
                <button
                  onClick={() => { setShowNewTopicForm(v => !v); setTopicMsg(null) }}
                  className="flex items-center gap-1.5 text-sm font-bold bg-(--brand) text-white rounded-xl hover:bg-(--brand-hover) transition"
                  style={{ padding: '8px 16px' }}
                >
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}><path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
                  Topic 추가
                </button>
              </div>

              {topicMsg && (
                <div className={`text-xs font-medium px-4 py-2 rounded-xl shrink-0 ${topicMsg.type === 'success' ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'}`} style={{ marginBottom: '12px' }}>
                  {topicMsg.text}
                </div>
              )}

              {/* 새 topic 폼 */}
              {showNewTopicForm && (
                <div className="border border-(--brand-a20) bg-(--brand-a5) rounded-xl shrink-0" style={{ padding: '16px', marginBottom: '16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <p className="text-xs font-black text-(--brand)">새 Topic 추가</p>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <label className="text-xs font-bold text-(--text-muted) block" style={{ marginBottom: '4px' }}>name (영문, 언더바)</label>
                      <input value={newTopic.name} onChange={e => setNewTopic(v => ({ ...v, name: e.target.value }))} placeholder="예: tuition" className="w-full text-sm border border-(--border) rounded-lg outline-none focus:border-(--brand)" style={{ padding: '6px 10px' }} />
                    </div>
                    <div>
                      <label className="text-xs font-bold text-(--text-muted) block" style={{ marginBottom: '4px' }}>label (한글 표시명)</label>
                      <input value={newTopic.label} onChange={e => setNewTopic(v => ({ ...v, label: e.target.value }))} placeholder="예: 등록금" className="w-full text-sm border border-(--border) rounded-lg outline-none focus:border-(--brand)" style={{ padding: '6px 10px' }} />
                    </div>
                  </div>
                  <div>
                    <label className="text-xs font-bold text-(--text-muted) block" style={{ marginBottom: '4px' }}>설명 (선택)</label>
                    <input value={newTopic.description} onChange={e => setNewTopic(v => ({ ...v, description: e.target.value }))} placeholder="이 topic에 대한 간단한 설명" className="w-full text-sm border border-(--border) rounded-lg outline-none focus:border-(--brand)" style={{ padding: '6px 10px' }} />
                  </div>
                  <div>
                    <label className="text-xs font-bold text-(--text-muted) block" style={{ marginBottom: '4px' }}>분류 문장 (한 줄에 하나씩)</label>
                    <textarea
                      value={newTopic.sentences}
                      onChange={e => setNewTopic(v => ({ ...v, sentences: e.target.value }))}
                      placeholder={"등록금 납부 방법이 궁금해요\n등록금은 언제까지 내야 하나요?"}
                      rows={4}
                      className="w-full text-sm border border-(--border) rounded-lg outline-none focus:border-(--brand) resize-none"
                      style={{ padding: '7px 10px' }}
                    />
                  </div>
                  <div className="flex gap-2 justify-end">
                    <button onClick={() => setShowNewTopicForm(false)} className="text-xs text-(--text-faint) border border-(--border) rounded-lg hover:bg-(--surface-2)" style={{ padding: '6px 14px' }}>취소</button>
                    <button onClick={handleCreateTopic} disabled={!newTopic.name || !newTopic.label} className="text-xs font-bold bg-(--brand) text-white rounded-lg hover:bg-(--brand-hover) disabled:opacity-40" style={{ padding: '6px 14px' }}>추가</button>
                  </div>
                </div>
              )}

              {/* Topic 목록 */}
              <div className="flex-1 overflow-y-auto" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {topicList.length === 0 ? (
                  <div className="flex items-center justify-center text-(--text-faint)" style={{ padding: '60px 0' }}>
                    <p className="text-sm">topic이 없습니다</p>
                  </div>
                ) : topicList.map(t => (
                  <div key={t.name} className="border border-(--border) rounded-xl bg-(--surface-2)/50 hover:bg-(--surface-card) transition" style={{ padding: '14px 16px' }}>
                    {editingTopic?.name === t.name ? (
                      // 수정 폼
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        <div className="grid grid-cols-2 gap-2">
                          <div>
                            <label className="text-xs font-bold text-(--text-muted) block" style={{ marginBottom: '3px' }}>label</label>
                            <input value={editingTopic.label} onChange={e => setEditingTopic(v => ({ ...v, label: e.target.value }))} className="w-full text-sm border border-(--border) rounded-lg outline-none focus:border-(--brand)" style={{ padding: '5px 8px' }} />
                          </div>
                          <div>
                            <label className="text-xs font-bold text-(--text-muted) block" style={{ marginBottom: '3px' }}>설명</label>
                            <input value={editingTopic.description || ''} onChange={e => setEditingTopic(v => ({ ...v, description: e.target.value }))} className="w-full text-sm border border-(--border) rounded-lg outline-none focus:border-(--brand)" style={{ padding: '5px 8px' }} />
                          </div>
                        </div>
                        <div>
                          <label className="text-xs font-bold text-(--text-muted) block" style={{ marginBottom: '3px' }}>분류 문장 (한 줄에 하나)</label>
                          <textarea
                            value={editingTopic.sentences}
                            onChange={e => setEditingTopic(v => ({ ...v, sentences: e.target.value }))}
                            rows={4}
                            className="w-full text-sm border border-(--border) rounded-lg outline-none focus:border-(--brand) resize-none"
                            style={{ padding: '6px 8px' }}
                          />
                        </div>
                        <div className="flex gap-2 justify-end">
                          <button onClick={() => setEditingTopic(null)} className="text-xs text-(--text-faint) border border-(--border) rounded-lg hover:bg-(--surface-2)" style={{ padding: '5px 12px' }}>취소</button>
                          <button
                            onClick={() => handleUpdateTopic(t.name, {
                              label: editingTopic.label,
                              description: editingTopic.description,
                              sentences: editingTopic.sentences.split('\n').map(s => s.trim()).filter(Boolean),
                            })}
                            className="text-xs font-bold bg-(--brand) text-white rounded-lg hover:bg-(--brand-hover)"
                            style={{ padding: '5px 12px' }}
                          >저장</button>
                        </div>
                      </div>
                    ) : (
                      // 표시 모드
                      <div className="flex items-start justify-between gap-4">
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div className="flex items-center gap-2" style={{ marginBottom: '4px' }}>
                            <span className="text-sm font-black text-(--text)">{t.label}</span>
                            <code className="text-xs bg-(--surface-2) text-(--text-muted) px-1.5 py-0.5 rounded">{t.name}</code>
                            <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
                              t.handler_type === 'campus' ? 'bg-blue-100 text-blue-700' :
                              t.handler_type === 'graduation' ? 'bg-purple-100 text-purple-700' :
                              t.handler_type === 'scholarship' ? 'bg-yellow-100 text-yellow-700' :
                              t.handler_type === 'general' ? 'bg-(--surface-2) text-(--text-muted)' :
                              'bg-emerald-100 text-emerald-700'
                            }`}>{t.handler_type}</span>
                            {t.is_system && <span className="text-xs bg-orange-100 text-orange-600 font-bold px-2 py-0.5 rounded-full">시스템</span>}
                            {!t.is_active && <span className="text-xs bg-red-100 text-red-500 font-bold px-2 py-0.5 rounded-full">비활성</span>}
                          </div>
                          {t.description && <p className="text-xs text-(--text-faint)" style={{ marginBottom: '6px' }}>{t.description}</p>}
                          <p className="text-xs text-(--text-faint)">{t.sentences?.length || 0}개 분류 문장</p>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <button
                            onClick={() => setEditingTopic({ name: t.name, label: t.label, description: t.description || '', sentences: (t.sentences || []).join('\n') })}
                            className="text-xs text-(--text-muted) border border-(--border) rounded-lg hover:bg-(--surface-2) transition"
                            style={{ padding: '5px 10px' }}
                          >수정</button>
                          {!t.is_system && (
                            <button
                              onClick={() => handleDeleteTopic(t.name)}
                              className="text-xs text-red-400 border border-red-100 rounded-lg hover:bg-red-50 transition"
                              style={{ padding: '5px 10px' }}
                            >삭제</button>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          </div>
        </main>
      </div>
    </div>
  )
}
