import { useState, useEffect, useCallback, useRef } from 'react'
import { getScholarships } from '../../api/scholarship'

const TEAL = 'var(--brand)'

/** 표준 드롭다운 셰브론(아래 방향). open이면 180° 회전해 위를 가리킨다.
 *  기존 '⌄'(U+2304) 글자는 폰트마다 얇은 캐럿(^)처럼 렌더돼 부자연스러웠다 → SVG로 일관되게. */
function Chevron({ open, size = 14, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
      style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .2s', flexShrink: 0 }}
      aria-hidden="true">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

/** 인증 헤더로 파일 다운로드 (a href 직접 연결은 Authorization 미전송) */
async function downloadFileWithAuth(topic, filename) {
  const token = sessionStorage.getItem('wsu_token')
  try {
    const res = await fetch(`/api/files/${encodeURIComponent(topic)}/${encodeURIComponent(filename)}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!res.ok) throw new Error('다운로드 실패')
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch {
    alert('파일 다운로드에 실패했습니다.')
  }
}

/** 표시용: 확장자 제거 (다운로드 파일명은 원본 유지) */
function stripExt(name) {
  return name.replace(/\.[^.]+$/, '')
}

/** 검색어 매칭 부분 하이라이트 */
function highlight(text, q) {
  if (!q || !text) return text
  const i = text.toLowerCase().indexOf(q.toLowerCase())
  if (i < 0) return text
  return (
    <>
      {text.slice(0, i)}
      <span style={{ background: 'var(--brand-tint2)', color: TEAL, borderRadius: '3px', padding: '0 2px' }}>{text.slice(i, i + q.length)}</span>
      {text.slice(i + q.length)}
    </>
  )
}

// 모달 정적 라벨 다국어. kind('장학금'/'근로')·scope('교내'/'교외')는 API 값이라 그대로 두고
// 표시 텍스트만 번역한다(동적 데이터 — 장학금명·조건·카테고리 등은 백엔드 값 그대로).
const MT = {
  ko: { title: '장학금 둘러보기', subtitle: '우송대학교 장학금 안내', close: '닫기',
        scholarship: '장학금', work: '근로', inSchool: '교내', outSchool: '교외',
        searchHint: '검색 (이름·조건)', clearSearch: '검색어 지우기', hideExpired: '기간마감 숨기기',
        loading: '불러오는 중…', loadFail: '불러오지 못했어요.',
        noSearch: (q) => `'${q}' 검색 결과가 없어요.`,
        noVisible: '표시할 항목이 없어요. (기간마감 숨김 해제해 보세요)',
        noItems: (k) => `등록된 ${k} 항목이 없어요.`,
        expired: '기간마감', condition: '조건', detailNote: '세부 내용은 첨부된 공고문을 확인해 주세요',
        files: '첨부파일', viewNotice: '공고 보기' },
  en: { title: 'Scholarships', subtitle: 'Woosong Univ. scholarship info', close: 'Close',
        scholarship: 'Scholarship', work: 'Work-Study', inSchool: 'On-campus', outSchool: 'Off-campus',
        searchHint: 'Search (name/condition)', clearSearch: 'Clear search', hideExpired: 'Hide expired',
        loading: 'Loading…', loadFail: 'Failed to load.',
        noSearch: (q) => `No results for '${q}'.`,
        noVisible: 'Nothing to show. (Try unhiding expired items)',
        noItems: (k) => `No ${k} items registered.`,
        expired: 'Expired', condition: 'Eligibility', detailNote: 'See the attached notice for details',
        files: 'Attachments', viewNotice: 'View notice' },
  zh: { title: '奖学金浏览', subtitle: '又松大学奖学金信息', close: '关闭',
        scholarship: '奖学金', work: '勤工俭学', inSchool: '校内', outSchool: '校外',
        searchHint: '搜索（名称·条件）', clearSearch: '清除搜索', hideExpired: '隐藏已截止',
        loading: '加载中…', loadFail: '加载失败。',
        noSearch: (q) => `没有 '${q}' 的搜索结果。`,
        noVisible: '没有可显示的项目。（请尝试取消隐藏已截止项目）',
        noItems: (k) => `没有已登记的${k}项目。`,
        expired: '已截止', condition: '条件', detailNote: '详细内容请查看附件公告',
        files: '附件', viewNotice: '查看公告' },
}

export default function ScholarshipModal({ lang = 'ko', initialScope = '교내', initialCategories = null, initialQuery = '', onBack, onClose }) {
  const mt = MT[lang] || MT.ko
  const kind = '장학금'   // 근로 롤백 — 장학금 전용 모달
  const [scope, setScope] = useState(initialScope) // '전체' | '교내' | '교외'
  const [catFilter, setCatFilter] = useState(initialCategories || [])  // 선택된 유형(카테고리) 필터 — 채팅 카드가 초기값 지정
  const [query, setQuery] = useState(initialQuery || '')   // 딥링크: 특정 장학금 이름으로 열기
  const [data, setData] = useState(null)      // { count, groups, counts }
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [openCats, setOpenCats] = useState({})  // { category: bool }
  const [openFiles, setOpenFiles] = useState({})  // { itemId: bool } 파일 세트 펼침
  const [hideExpired, setHideExpired] = useState(false)  // '기간마감 숨기기' 토글
  const [isDesktop, setIsDesktop] = useState(
    typeof window !== 'undefined' ? window.matchMedia('(min-width: 768px)').matches : true
  )  // 데스크톱이면 사이드바(264+24=288px)만큼 왼쪽을 비워 메인 카드 영역 중앙에 띄운다
  const debounceRef = useRef(null)
  const groupRefs = useRef({})   // 카테고리별 DOM ref — 퀵네비 점프(scrollIntoView)용

  const load = useCallback(async (kindArg, scopeArg, q) => {
    setLoading(true)
    setError(null)
    try {
      const res = await getScholarships(kindArg, scopeArg, q)
      setData(res)
      // 검색 중이면 결과가 보이도록 전부 펼치고, 아니면 전부 접는다.
      if (q) {
        const all = {}
        for (const g of res.groups) all[g.category] = true
        setOpenCats(all)
      } else {
        setOpenCats({})
      }
    } catch (e) {
      setError(e.message || (MT[lang] || MT.ko).loadFail)
    } finally {
      setLoading(false)
    }
  }, [lang])

  // scope 전환 시 '현재 검색어'로 로드한다. scope 탭은 클릭 시 스스로 setQuery('')를 호출해 검색을 비우므로
  // 여기서 따로 초기화할 필요가 없다. 최초 마운트 땐 query가 initialQuery(딥링크)라 그 장학금만 필터돼 열린다.
  // (검색어를 deps에 넣지 않아 타이핑마다 재로드하지 않는다 — 타이핑은 onSearch가 디바운스로 처리)
  useEffect(() => { load(kind, scope, query) }, [kind, scope, load])   // eslint-disable-line react-hooks/exhaustive-deps

  // 반응형 사이드바 추적 (전역 * {padding:0} 리셋이 Tailwind를 덮어써 인라인 padding으로 위치 보정)
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 768px)')
    const onChange = (e) => setIsDesktop(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // 검색어 디바운스
  function onSearch(v) {
    setQuery(v)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => load(kind, scope, v.trim()), 250)
  }

  const counts = data?.counts || {}
  const kindCounts = data?.kind_counts || {}

  // '기간마감 숨기기' 적용 후 화면에 보일 그룹 (빈 그룹 제거)
  const baseGroups = (data?.groups || [])
    .map((g) => ({ ...g, items: hideExpired ? g.items.filter((it) => !it.expired) : g.items }))
    .filter((g) => g.items.length > 0)
  const allCats = baseGroups.map((g) => g.category)   // 필터 칩 후보 (현재 로드된 전체 카테고리)
  const visibleGroups = catFilter.length
    ? baseGroups.filter((g) => catFilter.includes(g.category))   // 선택 유형만
    : baseGroups
  const visibleCount = visibleGroups.reduce((n, g) => n + g.items.length, 0)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'var(--scrim)', paddingLeft: isDesktop ? '288px' : '16px', paddingRight: '16px' }}
      onClick={onClose}
    >
      <div
        className="bg-(--surface-modal) rounded-2xl shadow-2xl border border-(--modal-edge) overflow-hidden flex flex-col"
        style={{ width: '100%', maxWidth: '820px', height: '82vh', maxHeight: '760px' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 헤더 */}
        <div className="flex items-center gap-3 border-b border-(--border) shrink-0" style={{ padding: '16px 18px' }}>
          {onBack && (
            <button onClick={onBack} className="text-(--text-faint) hover:text-(--text-body) shrink-0" aria-label="뒤로" title="설문 결과로 돌아가기">
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" /></svg>
            </button>
          )}
          <div className="flex items-center justify-center rounded-lg shrink-0" style={{ width: '34px', height: '34px', background: TEAL }}>
            <span className="emoji" style={{ fontSize: '18px' }}>🎓</span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-bold text-(--text)" style={{ fontSize: '15px' }}>{mt.title}</p>
            <p className="text-(--text-faint)" style={{ fontSize: '12px' }}>{mt.subtitle}</p>
          </div>
          <button onClick={onClose} className="text-(--text-faint) hover:text-(--text-body) text-lg" aria-label={mt.close}>✕</button>
        </div>

        {/* 탭 + 검색 */}
        <div className="border-b border-(--border) shrink-0" style={{ padding: '12px 18px' }}>
          <div className="flex items-center gap-2" style={{ marginBottom: '10px' }}>
            {['전체', '교내', '교외'].map((s) => {
              const active = scope === s
              const label = s === '전체' ? ({ ko: '전체', en: 'All', zh: '全部' }[lang] || '전체')
                : s === '교내' ? mt.inSchool : mt.outSchool
              const cnt = s === '전체' ? ((counts['교내'] || 0) + (counts['교외'] || 0)) : counts[s]
              return (
                <button
                  key={s}
                  onClick={() => { setQuery(''); setCatFilter([]); setScope(s) }}
                  className="font-semibold transition"
                  style={{
                    fontSize: '13px', padding: '6px 16px', borderRadius: '999px',
                    background: active ? TEAL : 'var(--surface-2)',
                    color: active ? '#fff' : 'var(--text-muted)',
                  }}
                >
                  {label}{cnt != null ? ` ${cnt}` : ''}
                </button>
              )
            })}
          </div>
          <div className="flex items-center gap-2 rounded-full border border-(--border)" style={{ padding: '7px 12px' }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-faint)" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" strokeLinecap="round" /></svg>
            <input
              value={query}
              onChange={(e) => onSearch(e.target.value)}
              placeholder={`${mt.scholarship} ${mt.searchHint}`}
              className="flex-1 outline-none bg-transparent text-(--text-body)"
              style={{ fontSize: '13px' }}
            />
            {query && (
              <button onClick={() => onSearch('')} className="text-(--text-faint) hover:text-(--text-muted)" aria-label={mt.clearSearch}>✕</button>
            )}
          </div>
          <label className="flex items-center gap-1.5 cursor-pointer select-none w-fit" style={{ marginTop: '9px', fontSize: '12px', color: 'var(--text-muted)' }}>
            <input type="checkbox" checked={hideExpired} onChange={(e) => setHideExpired(e.target.checked)} style={{ accentColor: TEAL }} />
            {mt.hideExpired}
          </label>
        </div>

        {/* 유형(카테고리) 필터 — 다중선택. 선택하면 그 유형만 목록에 남는다(스크롤 대신 필터). */}
        {!loading && !error && allCats.length > 1 && (
          <div className="flex items-center gap-1.5 border-b border-(--border) shrink-0 overflow-x-auto" style={{ padding: '8px 18px' }}>
            {allCats.map((cat) => {
              const on = catFilter.includes(cat)
              return (
                <button
                  key={cat}
                  onClick={() => setCatFilter((p) => (on ? p.filter((c) => c !== cat) : [...p, cat]))}
                  className="shrink-0 rounded-full border transition"
                  style={{
                    fontSize: '11px', padding: '3px 10px', whiteSpace: 'nowrap',
                    borderColor: on ? 'var(--brand)' : 'var(--modal-edge)',
                    background: on ? 'var(--brand)' : 'transparent',
                    color: on ? '#fff' : 'var(--text-muted)',
                    fontWeight: on ? 700 : 500,
                  }}
                >
                  {cat}
                </button>
              )
            })}
            {catFilter.length > 0 && (
              <button
                onClick={() => setCatFilter([])}
                className="shrink-0 text-(--text-faint) hover:text-(--text-muted) transition"
                style={{ fontSize: '11px', padding: '3px 6px', whiteSpace: 'nowrap' }}
              >
                초기화 ✕
              </button>
            )}
          </div>
        )}

        {/* 본문 */}
        <div style={{ padding: '12px 18px 18px', overflowY: 'auto' }}>
          {loading && <p className="text-center text-(--text-faint)" style={{ fontSize: '13px', padding: '30px' }}>{mt.loading}</p>}
          {error && !loading && <p className="text-center text-red-400" style={{ fontSize: '13px', padding: '30px' }}>{error}</p>}
          {!loading && !error && visibleCount === 0 && (
            <p className="text-center text-(--text-faint)" style={{ fontSize: '13px', padding: '30px' }}>
              {query ? mt.noSearch(query)
                : (hideExpired && data?.count > 0) ? mt.noVisible
                : mt.noItems(mt.scholarship)}
            </p>
          )}

          {!loading && !error && visibleGroups.map((g) => {
            const open = !!openCats[g.category]
            return (
              <div key={g.category} ref={(el) => { groupRefs.current[g.category] = el }} className="rounded-xl overflow-hidden" style={{ marginBottom: '14px', border: '1px solid var(--modal-edge)' }}>
                <button
                  onClick={() => setOpenCats((p) => ({ ...p, [g.category]: !p[g.category] }))}
                  className="flex items-center gap-2 w-full transition hover:brightness-95"
                  style={{ padding: '11px 14px', background: 'var(--cat-header)' }}
                >
                  <span className="font-bold" style={{ fontSize: '14px', color: TEAL }}>{g.category}</span>
                  <span className="rounded-full font-semibold text-white" style={{ fontSize: '11px', padding: '1px 9px', background: TEAL }}>{g.items.length}</span>
                  <span className="flex-1" />
                  <Chevron open={open} size={16} color={TEAL} />
                </button>

                {open && (
                  <div style={{ padding: '8px 12px 10px' }}>
                    {g.items.map((it) => {
                      const files = it.files || []
                      const filesOpen = !!openFiles[it.id]
                      return (
                      <div key={it.id} className="rounded-2xl" style={{ padding: '14px 16px', marginBottom: '10px', background: 'var(--item-bubble)', boxShadow: 'var(--item-shadow)' }}>
                        <div className="flex items-center flex-wrap" style={{ columnGap: '8px', rowGap: '4px' }}>
                          <span className="font-medium text-(--text)" style={{ fontSize: '13px' }}>{highlight(it.name, query)}</span>
                          {it.amount && <span className="font-semibold rounded-full shrink-0" style={{ fontSize: '11px', padding: '2px 9px', background: 'var(--brand-tint2)', color: TEAL }}>{it.amount}</span>}
                        </div>
                        {/* 기간 + 마감 */}
                        {(it.period || it.expired) && (
                          <div className="flex items-center flex-wrap gap-2" style={{ marginTop: '6px' }}>
                            {it.period && (
                              <span className="rounded-full inline-flex items-center gap-1" style={{ fontSize: '11px', padding: '2px 9px', background: it.expired ? 'var(--danger-tint)' : 'var(--amber-tint)', color: it.expired ? 'var(--danger-text)' : 'var(--amber-text)' }}>
                                <span className="emoji">🗓</span> {it.period}
                              </span>
                            )}
                            {it.expired && (
                              <span className="rounded-full font-semibold" style={{ fontSize: '11px', padding: '1px 8px', background: 'var(--danger-tint)', color: 'var(--danger-text)' }}>{mt.expired}</span>
                            )}
                          </div>
                        )}

                        {/* 조건 */}
                        {it.eligibility && (
                          <p className="text-(--text-muted)" style={{ fontSize: '12px', marginTop: '7px' }}>
                            <span className="text-(--text-faint)">{mt.condition} : </span>{highlight(it.eligibility, query)}
                          </p>
                        )}

                        {/* 안내 문구 */}
                        {files.length > 0 && (
                          <p className="text-(--text-faint)" style={{ fontSize: '11px', marginTop: '3px' }}>{mt.detailNote}</p>
                        )}

                        {/* 액션: 첨부파일 · 공고 링크 */}
                        {(files.length > 0 || it.link) && (
                          <div className="flex items-center flex-wrap gap-2" style={{ marginTop: '10px' }}>
                            {files.length > 0 && (
                              <button
                                onClick={() => setOpenFiles((p) => ({ ...p, [it.id]: !p[it.id] }))}
                                className="inline-flex items-center gap-1 rounded-full hover:bg-(--brand-tint) transition"
                                style={{ fontSize: '11px', padding: '3px 11px', color: TEAL, border: `1px solid ${TEAL}` }}
                              >
                                <span className="emoji">📎</span> {mt.files} {files.length}
                                <Chevron open={filesOpen} size={12} />
                              </button>
                            )}
                            {it.link && (
                              <a
                                href={it.link} target="_blank" rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 rounded-full hover:bg-(--brand-tint) transition"
                                style={{ fontSize: '11px', padding: '3px 11px', color: TEAL, border: `1px solid ${TEAL}`, textDecoration: 'none' }}
                              >
                                <span className="emoji">🔗</span> {mt.viewNotice}
                              </a>
                            )}
                          </div>
                        )}

                        {/* 펼친 첨부파일 목록 (전체) */}
                        {filesOpen && files.length > 0 && (
                          <div className="flex flex-col rounded-lg" style={{ gap: '2px', marginTop: '8px', padding: '8px 10px', background: 'var(--surface-2)' }}>
                            {files.map((f) => (
                              <button
                                key={f.name}
                                onClick={() => downloadFileWithAuth(f.topic, f.name)}
                                className="inline-flex items-center gap-1.5 text-left hover:text-(--brand) transition"
                                style={{ fontSize: '12px', color: 'var(--text-muted)', padding: '2px 0' }}
                                title={f.name}
                              >
                                <span className="emoji shrink-0" style={{ color: TEAL }}>📄</span>
                                <span className="truncate" style={{ maxWidth: '340px' }}>{stripExt(f.name)}</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
