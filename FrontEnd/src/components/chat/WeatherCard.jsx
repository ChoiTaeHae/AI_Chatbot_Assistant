/* 캠퍼스 날씨 카드.
 *
 * 텍스트 답변과 함께 나가는 '덧붙임'이다 — 이 컴포넌트가 없어도 대화는 성립한다.
 * 그래서 값이 비면 그 줄만 빠지고 카드 전체가 깨지지 않게 전부 옵셔널로 읽는다.
 *
 * 아이콘은 이모지를 쓴다. 이미지 URL을 쓰면 외부 요청이 한 번 더 생기고(느려지고
 * 차단될 수 있다) 다크모드에서 흰 배경이 뜬다.
 *
 * 여백은 전역 `* { padding: 0 }` 리셋이 Tailwind 유틸을 덮어써서 인라인 style로 준다.
 */

const T = {
  ko: { feels: '체감', humid: '습도', wind: '바람', fine: '미세', ultra: '초미세',
        sun: '일출/일몰', tomorrow: '내일', am: '오전', pm: '오후', low: '최저', high: '최고' },
  en: { feels: 'Feels', humid: 'Humidity', wind: 'Wind', fine: 'PM10', ultra: 'PM2.5',
        sun: 'Sunrise/Sunset', tomorrow: 'Tomorrow', am: 'AM', pm: 'PM', low: 'Low', high: 'High' },
  zh: { feels: '体感', humid: '湿度', wind: '风', fine: 'PM10', ultra: 'PM2.5',
        sun: '日出/日落', tomorrow: '明天', am: '上午', pm: '下午', low: '最低', high: '最高' },
}

// 미세먼지 등급별 색. '좋음'만 파랑, 나머지는 단계적으로 붉어진다 —
// 네 단계를 모두 다른 색으로 칠하면 어느 쪽이 나쁜 건지 한눈에 안 들어온다.
const GRADE_COLOR = {
  좋음: '#2E7D52', 보통: '#8A8A8A', 나쁨: '#C77700', 매우나쁨: '#C0392B',
}

function Stat({ label, value, color }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className="flex flex-col items-center" style={{ gap: '3px', minWidth: '54px' }}>
      <span className="text-(--text-faint)" style={{ fontSize: '10px' }}>{label}</span>
      <span className="font-bold" style={{ fontSize: '12px', color: color || 'var(--text-body)' }}>
        {value}
      </span>
    </div>
  )
}

export default function WeatherCard({ card, lang = 'ko' }) {
  if (!card) return null
  const t = T[lang] || T.ko
  const { hourly = [], tomorrow } = card

  return (
    <div className="border border-(--border) rounded-2xl overflow-hidden bg-(--surface-card)"
         style={{ marginTop: '10px' }}>

      {/* 현재 — 기온을 가장 크게. 사용자가 카드를 열어 제일 먼저 보는 값이다 */}
      <div style={{ padding: '14px 16px 12px' }}>
        <p className="text-(--text-faint)" style={{ fontSize: '11px' }}>
          {card.place}{card.date ? ` · ${card.date}` : ''}
        </p>
        <div className="flex items-center" style={{ gap: '12px', marginTop: '6px' }}>
          <span style={{ fontSize: '38px', lineHeight: 1 }}>{card.emoji}</span>
          <div>
            <div className="flex items-baseline" style={{ gap: '7px' }}>
              <span className="font-black text-(--text)" style={{ fontSize: '30px', lineHeight: 1 }}>
                {card.temp}°
              </span>
              <span className="text-(--text-muted)" style={{ fontSize: '13px' }}>{card.desc}</span>
            </div>
            <p className="text-(--text-faint)" style={{ fontSize: '11px', marginTop: '4px' }}>
              {card.feels_like != null && `${t.feels} ${card.feels_like}°`}
              {card.temp_min != null && card.temp_max != null &&
                `  ·  ${t.low} ${card.temp_min}° / ${t.high} ${card.temp_max}°`}
            </p>
          </div>
        </div>
      </div>

      {/* 지표 — 값이 없는 항목은 Stat이 스스로 빠진다 */}
      <div className="flex flex-wrap items-center border-t border-(--border)"
           style={{ gap: '4px', padding: '10px 12px', justifyContent: 'space-around' }}>
        <Stat label={t.humid} value={card.humidity != null ? `${card.humidity}%` : null} />
        <Stat label={t.wind} value={card.wind != null ? `${card.wind}m/s` : null} />
        <Stat label={t.fine} value={card.pm10} color={GRADE_COLOR[card.pm10]} />
        <Stat label={t.ultra} value={card.pm25} color={GRADE_COLOR[card.pm25]} />
        <Stat label={t.sun}
              value={card.sunrise && card.sunset ? `${card.sunrise}/${card.sunset}` : null} />
      </div>

      {/* 시간별 — 3시간 간격 8칸. 폰에서는 가로 스크롤로 넘긴다 */}
      {hourly.length > 0 && (
        <div className="border-t border-(--border)" style={{ padding: '10px 0' }}>
          <div className="flex" style={{ overflowX: 'auto', gap: '2px', padding: '0 8px' }}>
            {hourly.map((h, i) => (
              <div key={i} className="flex flex-col items-center shrink-0"
                   style={{ gap: '3px', minWidth: '48px' }}>
                <span className="text-(--text-faint)" style={{ fontSize: '10px' }}>{h.time}</span>
                <span style={{ fontSize: '17px', lineHeight: 1.1 }}>{h.emoji}</span>
                <span className="font-bold text-(--text-body)" style={{ fontSize: '12px' }}>{h.temp}°</span>
                {/* 강수확률은 0%일 때 숨긴다 — 안 오는 날 0이 줄줄이 뜨면 잡음이다 */}
                <span style={{ fontSize: '9px', color: h.pop >= 60 ? 'var(--brand)' : 'var(--text-faint)' }}>
                  {h.pop > 0 ? `${h.pop}%` : ' '}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 내일 — 오전/오후를 나눈다. 하루 최대만 쓰면 오후에만 오는 비가 종일 비로 읽힌다 */}
      {tomorrow && (
        <div className="flex items-center border-t border-(--border)"
             style={{ padding: '10px 16px', gap: '10px' }}>
          <span className="text-(--text-faint) shrink-0" style={{ fontSize: '11px' }}>
            {t.tomorrow} {tomorrow.date}
          </span>
          <span style={{ fontSize: '17px' }}>{tomorrow.emoji}</span>
          <span className="font-bold text-(--text-body)" style={{ fontSize: '12px' }}>
            {tomorrow.min}° / {tomorrow.max}°
          </span>
          <span className="text-(--text-faint)" style={{ fontSize: '11px', marginLeft: 'auto' }}>
            {t.am} {tomorrow.am_pop}%  ·  {t.pm} {tomorrow.pm_pop}%
          </span>
        </div>
      )}
    </div>
  )
}
