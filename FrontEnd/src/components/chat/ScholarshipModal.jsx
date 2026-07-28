import { useState, useEffect, useCallback, useRef } from 'react'
import { getScholarships } from '../../api/scholarship'

const TEAL = 'var(--brand)'

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

export default function ScholarshipModal({ onClose }) {
  const [kind, setKind] = useState('장학금')   // 상단 전환: '장학금' | '근로'
  const [scope, setScope] = useState('교내')
  const [query, setQuery] = useState('')
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
      setError(e.message || '불러오지 못했어요.')
    } finally {
      setLoading(false)
    }
  }, [])

  // kind/scope 전환 시 즉시 로드 (검색어 초기화)
  useEffect(() => { setQuery(''); load(kind, scope, '') }, [kind, scope, load])

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
  const visibleGroups = (data?.groups || [])
    .map((g) => ({ ...g, items: hideExpired ? g.items.filter((it) => !it.expired) : g.items }))
    .filter((g) => g.items.length > 0)
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
          <div className="flex items-center justify-center rounded-lg shrink-0" style={{ width: '34px', height: '34px', background: TEAL }}>
            <span style={{ fontSize: '18px' }}>🎓</span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="font-bold text-(--text)" style={{ fontSize: '15px' }}>장학금·근로 둘러보기</p>
            <p className="text-(--text-faint)" style={{ fontSize: '12px' }}>우송대학교 장학·근로 안내</p>
          </div>
          <button onClick={onClose} className="text-(--text-faint) hover:text-(--text-body) text-lg" aria-label="닫기">✕</button>
        </div>

        {/* 상단 전환: 장학금 / 근로 */}
        <div className="flex items-center gap-2 border-b border-(--border) shrink-0" style={{ padding: '12px 18px' }}>
          {[['장학금', '🎓'], ['근로', '💼']].map(([k, icon]) => {
            const active = kind === k
            return (
              <button
                key={k}
                onClick={() => { setScope('교내'); setKind(k) }}
                className="flex items-center gap-1.5 font-bold transition"
                style={{
                  fontSize: '14px', padding: '9px 18px', borderRadius: '12px', flex: 1, justifyContent: 'center',
                  background: active ? TEAL : 'var(--surface-2)',
                  color: active ? '#fff' : 'var(--text-muted)',
                }}
              >
                <span>{icon}</span>{k}{kindCounts[k] != null ? ` ${kindCounts[k]}` : ''}
              </button>
            )
          })}
        </div>

        {/* 탭 + 검색 */}
        <div className="border-b border-(--border) shrink-0" style={{ padding: '12px 18px' }}>
          <div className="flex items-center gap-2" style={{ marginBottom: '10px' }}>
            {['교내', '교외'].map((s) => {
              const active = scope === s
              return (
                <button
                  key={s}
                  onClick={() => { setQuery(''); setScope(s) }}
                  className="font-semibold transition"
                  style={{
                    fontSize: '13px', padding: '6px 16px', borderRadius: '999px',
                    background: active ? TEAL : 'var(--surface-2)',
                    color: active ? '#fff' : 'var(--text-muted)',
                  }}
                >
                  {s}{counts[s] != null ? ` ${counts[s]}` : ''}
                </button>
              )
            })}
          </div>
          <div className="flex items-center gap-2 rounded-full border border-(--border)" style={{ padding: '7px 12px' }}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--text-faint)" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" strokeLinecap="round" /></svg>
            <input
              value={query}
              onChange={(e) => onSearch(e.target.value)}
              placeholder={`${kind} 검색 (이름·조건)`}
              className="flex-1 outline-none bg-transparent text-(--text-body)"
              style={{ fontSize: '13px' }}
            />
            {query && (
              <button onClick={() => onSearch('')} className="text-(--text-faint) hover:text-(--text-muted)" aria-label="검색어 지우기">✕</button>
            )}
          </div>
          <label className="flex items-center gap-1.5 cursor-pointer select-none w-fit" style={{ marginTop: '9px', fontSize: '12px', color: 'var(--text-muted)' }}>
            <input type="checkbox" checked={hideExpired} onChange={(e) => setHideExpired(e.target.checked)} style={{ accentColor: TEAL }} />
            기간마감 숨기기
          </label>
        </div>

        {/* 본문 */}
        <div style={{ padding: '12px 18px 18px', overflowY: 'auto' }}>
          {loading && <p className="text-center text-(--text-faint)" style={{ fontSize: '13px', padding: '30px' }}>불러오는 중…</p>}
          {error && !loading && <p className="text-center text-red-400" style={{ fontSize: '13px', padding: '30px' }}>{error}</p>}
          {!loading && !error && visibleCount === 0 && (
            <p className="text-center text-(--text-faint)" style={{ fontSize: '13px', padding: '30px' }}>
              {query ? `'${query}' 검색 결과가 없어요.`
                : (hideExpired && data?.count > 0) ? '표시할 항목이 없어요. (기간마감 숨김 해제해 보세요)'
                : `등록된 ${kind} 항목이 없어요.`}
            </p>
          )}

          {!loading && !error && visibleGroups.map((g) => {
            const open = !!openCats[g.category]
            return (
              <div key={g.category} className="rounded-xl overflow-hidden" style={{ marginBottom: '14px', border: '1px solid var(--modal-edge)' }}>
                <button
                  onClick={() => setOpenCats((p) => ({ ...p, [g.category]: !p[g.category] }))}
                  className="flex items-center gap-2 w-full transition hover:brightness-95"
                  style={{ padding: '11px 14px', background: 'var(--cat-header)' }}
                >
                  <span className="font-bold" style={{ fontSize: '14px', color: TEAL }}>{g.category}</span>
                  <span className="rounded-full font-semibold text-white" style={{ fontSize: '11px', padding: '1px 9px', background: TEAL }}>{g.items.length}</span>
                  <span className="flex-1" />
                  <span style={{ color: TEAL, fontSize: '15px', transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }}>⌄</span>
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
                                🗓 {it.period}
                              </span>
                            )}
                            {it.expired && (
                              <span className="rounded-full font-semibold" style={{ fontSize: '11px', padding: '1px 8px', background: 'var(--danger-tint)', color: 'var(--danger-text)' }}>기간마감</span>
                            )}
                          </div>
                        )}

                        {/* 조건 */}
                        {it.eligibility && (
                          <p className="text-(--text-muted)" style={{ fontSize: '12px', marginTop: '7px' }}>
                            <span className="text-(--text-faint)">조건 : </span>{highlight(it.eligibility, query)}
                          </p>
                        )}

                        {/* 안내 문구 */}
                        {files.length > 0 && (
                          <p className="text-(--text-faint)" style={{ fontSize: '11px', marginTop: '3px' }}>세부 내용은 첨부된 공고문을 확인해 주세요</p>
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
                                📎 첨부파일 {files.length}
                                <span style={{ transform: filesOpen ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }}>⌄</span>
                              </button>
                            )}
                            {it.link && (
                              <a
                                href={it.link} target="_blank" rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 rounded-full hover:bg-(--brand-tint) transition"
                                style={{ fontSize: '11px', padding: '3px 11px', color: TEAL, border: `1px solid ${TEAL}`, textDecoration: 'none' }}
                              >
                                🔗 공고 보기
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
                                <span className="shrink-0" style={{ color: TEAL }}>📄</span>
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
