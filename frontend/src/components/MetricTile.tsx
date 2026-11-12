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
    <article className={`rounded-card border px-4 py-3 ${green ? 'border-transparent bg-panel2' : 'border-line bg-panel'}`}>
      <p className="text-xs font-normal leading-none text-mute">{label}</p>
      <p className="num mt-1 text-[28px] font-semibold leading-none text-paper">
        {shown}
        {suffix}
      </p>
      <p className="mt-1 text-xs leading-none text-mute">{hint}</p>
    </article>
  )
}
