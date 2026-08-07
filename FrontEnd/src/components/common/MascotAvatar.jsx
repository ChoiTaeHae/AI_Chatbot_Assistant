import mascotImg from '../../assets/Mascot_Profile.png'

export default function MascotAvatar({ className = 'h-10 w-10', style }) {
  return (
    <img
      src={mascotImg}
      alt="우송대학교 마스코트"
      className={className}
      style={style}
      draggable={false}
    />
  )
}
