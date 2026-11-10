import { useCountUp } from '../lib/useCountUp'

type MetricTileProps = {
  label: string
  value: number | null
  suffix: string
  hint: string
}

export function MetricTile({ label, value, suffix, hint }: MetricTileProps) {
  const counted = useCountUp(value ?? 0)
  const shown = value === null ? '—' : Number.isInteger(value) ? String(Math.round(counted)) : counted.toFixed(2)

  return (
    <article className="rounded-card border border-line bg-panel px-5 py-5">
      <h2 className="text-[13px] font-medium text-dim">{label}</h2>
      <p className="num mt-3 text-[32px] leading-none text-paper">
        {shown}
        {value === null ? '' : suffix}
      </p>
      <p className="mt-3 text-sm text-dim">{hint}</p>
    </article>
  )
}
