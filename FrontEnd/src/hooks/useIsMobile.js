import { useEffect, useState } from 'react'

/** 모바일 여부(기본 639px 이하 = Tailwind sm 미만).
 *
 *  왜 CSS가 아니라 JS로 판단하나
 *    index.css의 전역 리셋 `* { padding: 0 }`이 레이어 밖에 있어, 레이어(@layer utilities)에
 *    들어가는 Tailwind의 p- / m- 여백 유틸을 캐스케이드에서 무조건 이긴다. 그래서 이 프로젝트에서
 *    여백은 인라인 style로만 먹고, `px-3 sm:px-6` 같은 반응형 패딩 클래스는 아무 효과가 없다.
 *    → 반응형 여백은 이 훅으로 분기해 인라인 값으로 넣는다.
 *    (리셋은 Tailwind preflight와 중복이라 언젠가 걷어내면 유틸이 살아나지만, 그 순간 죽어
 *     있던 여백 클래스 70여 곳이 한꺼번에 되살아나므로 별도 작업으로 다뤄야 한다.)
 */
export default function useIsMobile(query = '(max-width: 639px)') {
  const [is, setIs] = useState(
    () => (typeof window === 'undefined' ? false : window.matchMedia(query).matches)
  )
  useEffect(() => {
    const mq = window.matchMedia(query)
    const onChange = (e) => setIs(e.matches)
    setIs(mq.matches)          // 훅 사용 중 query가 바뀐 경우 동기화
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [query])
  return is
}
