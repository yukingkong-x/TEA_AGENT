import { useEffect, useState } from 'react'
import { PageFrame } from '../components/PageFrame'
import { ReportTrend } from '../components/ReportTrend'
import { patrolReport, patrolRounds, type PatrolRound } from '../data/patrolReport'

function useGrow(ms = 1100) {
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) {
      setProgress(1)
      return
    }
    const start = performance.now()
    let frame = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ms)
      setProgress(1 - (1 - t) ** 3)
      if (t < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [ms])

  return progress
}

function RoundCard({ round }: { round: PatrolRound }) {
  const radius = 78
  const stroke = 22
  const cx = 112
  const cy = 124
  const width = 360
  const height = 268
  const labelX = 232
  const length = 2 * Math.PI * radius
  const turn = `rotate(-90 ${cx} ${cy})`
  const closed = round.rate >= 60
  const progress = useGrow()
  const edge = radius + stroke / 2
  const callouts = [
    { fraction: round.baseline / 200, color: '#1F7A45', name: '基线', value: round.baseline },
    { fraction: (round.baseline + round.measured) / 200, color: '#E4B423', name: '复测', value: round.measured },
  ].map((item) => {
    const angle = item.fraction * Math.PI * 2
    const reach = edge + 18
    return {
      ...item,
      x1: cx + Math.sin(angle) * edge,
      y1: cy - Math.cos(angle) * edge,
      x2: cx + Math.sin(angle) * reach,
      y2: cy - Math.cos(angle) * reach,
    }
  })
  if (Math.abs(callouts[0].y2 - callouts[1].y2) < 28) {
    const mid = (callouts[0].y2 + callouts[1].y2) / 2
    const upper = callouts[0].y2 <= callouts[1].y2 ? callouts[0] : callouts[1]
    const lower = upper === callouts[0] ? callouts[1] : callouts[0]
    upper.y2 = mid - 16
    lower.y2 = mid + 16
  }

  return (
    <section className="rounded-2xl bg-[#F7F8FA] px-4 py-4 sm:px-5 sm:py-5">
      <h2 className="text-center text-paper">第 {round.round} 轮</h2>
      <div className="relative mx-auto mt-2 w-full max-w-[420px]" style={{ aspectRatio: `${width} / ${height}` }}>
        <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full" aria-hidden="true">
          <circle cx={cx} cy={cy} r={radius} fill="none" stroke="#E7EEE9" strokeWidth={stroke} />
          <circle
            cx={cx}
            cy={cy}
            r={radius}
            fill="none"
            stroke="#E4B423"
            strokeWidth={stroke}
            strokeDasharray={`${length * (round.measured / 100) * progress} ${length}`}
            transform={turn}
          />
          <circle
            cx={cx}
            cy={cy}
            r={radius}
            fill="none"
            stroke="#1F7A45"
            strokeWidth={stroke}
            strokeDasharray={`${length * (round.baseline / 100) * progress} ${length}`}
            transform={turn}
          />
          {callouts.map((item) => {
            const ex = item.x1 + (item.x2 - item.x1) * progress
            const ey = item.y1 + (item.y2 - item.y1) * progress
            const tx = ex + (labelX - item.x2) * progress
            return (
              <g key={item.name}>
                <path d={`M ${item.x1} ${item.y1} L ${ex} ${ey} L ${tx} ${ey}`} fill="none" stroke={item.color} strokeWidth="1.5" />
                <text x={labelX + 8} y={item.y2} fill="#1D2129" fontSize="14" fontFamily="PingFang SC, Noto Sans SC, sans-serif" dominantBaseline="middle" opacity={progress}>
                  {item.name}{' '}
                  <tspan fontFamily="DIN, DIN Alternate, sans-serif">{item.value.toFixed(1)}%</tspan>
                </text>
              </g>
            )
          })}
        </svg>
        <div
          className="absolute -translate-x-1/2 -translate-y-1/2 text-center"
          style={{ left: `${(cx / width) * 100}%`, top: `${(cy / height) * 100}%` }}
        >
          <span className="num block text-[28px] font-semibold leading-none text-paper">{(round.rate * progress).toFixed(2)}%</span>
          <span className="mt-1 block text-xs leading-none text-mute">达成率</span>
        </div>
      </div>
      <div className="mt-3 overflow-hidden rounded-xl border border-line bg-panel">
        <table className="w-full border-collapse text-left text-sm leading-normal">
          <tbody>
            <tr>
              <th className="w-16 border-b border-line bg-[#F7F8FA] px-3 py-2.5 text-left text-sm font-normal text-dim">诊断</th>
              <td className="border-b border-line px-3 py-2.5 text-paper">{round.diagnosis}</td>
            </tr>
            <tr>
              <th className="w-16 border-b border-line bg-[#F7F8FA] px-3 py-2.5 text-left text-sm font-normal text-dim">修正</th>
              <td className="border-b border-line px-3 py-2.5 text-paper">{round.correction}</td>
            </tr>
            <tr>
              <th className="w-16 bg-[#F7F8FA] px-3 py-2.5 text-left text-sm font-normal text-dim">结果</th>
              <td className="px-3 py-2.5">
                <span className={`inline-flex h-6 items-center rounded-btn px-2 text-xs leading-none ${closed ? 'bg-panel2 text-tea' : 'bg-[#FFF4CC] text-[#8A6414]'}`}>
                  {closed ? '闭环' : '未达标'}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  )
}

export function ReportPage() {
  const second = patrolRounds[1]

  return (
    <PageFrame title="验证报告">
    <div className="flex flex-col gap-4 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-mute">{patrolReport.name}。第 2 轮复测 {second.measured.toFixed(1)}%。</p>
        <button type="button" className="h-11 rounded-btn bg-tea px-4 text-base text-white hover:bg-teaHover active:bg-teaPress" onClick={() => window.print()}>
          生成日报
        </button>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        {patrolRounds.map((round) => (
          <RoundCard key={round.round} round={round} />
        ))}
      </div>
      <section className="rounded-2xl bg-[#F7F8FA] px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-paper">湿度轨迹</h2>
          <p className="text-sm text-mute">两轮复测</p>
        </div>
        <ReportTrend />
      </section>
    </div>
    </PageFrame>
  )
}
