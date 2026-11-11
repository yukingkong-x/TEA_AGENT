import { useCountUp } from '../lib/useCountUp'

type MetricTileProps = {
  label: string
  value: number
  suffix: string
  hint: string
  tone?: 'plain' | 'green'
}

export function MetricTile({ label, value, suffix, hint, tone = 'plain' }: MetricTileProps) {
  const counted = useCountUp(value)
  const shown = Number.isInteger(value) ? String(Math.round(counted)) : counted.toFixed(2)
  const green = tone === 'green'

  return (
    <article className={`rounded-card border px-4 py-3 ${green ? 'border-transparent bg-[#DFF6E6]' : 'border-line bg-panel'}`}>
      <h2 className="text-[13px] font-medium text-dim">{label}</h2>
      <p className="num mt-1 text-[26px] leading-none tracking-tight text-paper">
        {shown}
        {suffix}
      </p>
      <p className="mt-1 text-[13px] text-dim">{hint}</p>
    </article>
  )
}
