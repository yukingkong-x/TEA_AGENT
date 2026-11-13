import { Link } from 'react-router-dom'
import { useCountUp } from '../lib/useCountUp'

type MetricTileProps = {
  label: string
  value: number
  suffix: string
  hint: string
  tone?: 'plain' | 'green' | 'yellow'
  to?: string
}

export function MetricTile({ label, value, suffix, hint, tone = 'plain', to }: MetricTileProps) {
  const counted = useCountUp(value)
  const shown = Number.isInteger(value) ? String(Math.round(counted)) : counted.toFixed(2)
  const surface =
    tone === 'green' ? 'border-transparent bg-panel2' : tone === 'yellow' ? 'border-transparent bg-[#FFF4CC]' : 'border-line bg-panel'
  const className = `rounded-card border px-4 py-3 ${surface}${to ? ' block cursor-pointer hover:border-tea' : ''}`
  const body = (
    <>
      <p className="text-xs font-normal leading-none text-mute">{label}</p>
      <p className="num mt-1 text-[28px] font-semibold leading-none text-paper">
        {shown}
        {suffix}
      </p>
      <p className="mt-1 text-xs leading-none text-mute">{hint}</p>
    </>
  )

  if (to) {
    return (
      <Link to={to} className={className}>
        {body}
      </Link>
    )
  }

  return <article className={className}>{body}</article>
}
