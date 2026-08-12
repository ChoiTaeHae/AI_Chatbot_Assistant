/* 관리자 화면 버튼 체계.
 *
 * 왜 한곳에 모았나
 *   FAQ 화면의 버튼들이 나란히 붙어 있는데 테두리 색이 3종(--border / --brand-a20 /
 *   --border+빨간 글자)이고 패딩도 6·10, 6·12, 8·12로 제각각이라 서로 따로 놀았다.
 *   각 컴포넌트가 클래스 문자열을 직접 쓰면 고칠 때마다 또 갈라진다.
 *
 * 규칙
 *   ① 채운 버튼(primary)은 화면 영역당 하나만. 목록 행마다 채운 버튼을 두면 줄 수만큼
 *      브랜드색이 반복돼 화면이 시끄럽고, 정작 무엇이 주 동작인지 알 수 없다.
 *   ② 행 액션은 전부 ghost — 평소엔 테두리 없는 회색 글자, hover에서만 배경이 뜬다.
 *      목록이 조용해지고 색은 '지금 누를 수 있는 것'에만 남는다.
 *   ③ 삭제도 평소엔 회색이고 hover에서만 빨강이 된다. 늘 빨간 버튼이 줄마다 있으면
 *      경고가 배경처럼 묻혀 정작 위험할 때 눈에 안 띈다.
 *   ④ 크기(padding·radius·font)는 종류와 무관하게 같다 — 높이가 다르면 한 줄에서 어긋난다.
 */

const BASE = 'rounded-lg text-xs font-bold transition whitespace-nowrap disabled:opacity-50'

export const BTN = {
  /** 주 동작 — 화면 영역당 하나 (예: + FAQ 추가) */
  primary: `${BASE} bg-(--brand) text-white hover:bg-(--brand-hover)`,
  /** 행의 기본 액션 (제외·비활성·되돌리기) */
  ghost: `${BASE} text-(--text-muted) hover:bg-(--surface-2) hover:text-(--text-body)`,
  /** 행에서 권하는 액션 (답변 작성·수정) — 색만으로 구분하고 채우지는 않는다 */
  ghostBrand: `${BASE} text-(--brand) hover:bg-(--brand-a10)`,
  /** 되돌릴 수 없는 액션 (삭제) — hover에서만 빨강 */
  ghostDanger: `${BASE} text-(--text-muted) hover:bg-(--danger-tint) hover:text-(--danger-text)`,
  /** 탭·필터처럼 선택 상태를 가지는 버튼 */
  tabOn: `${BASE} bg-(--brand) text-white`,
  tabOff: `${BASE} border border-(--border) text-(--text-muted) hover:bg-(--surface-2)`,
}

/** 모든 버튼이 같은 높이를 갖도록 크기는 여기서만 정한다. */
export const BTN_PAD = { padding: '7px 11px' }
export const BTN_PAD_LG = { padding: '10px 18px' }   // 헤더 주 동작 · 모달 확정
