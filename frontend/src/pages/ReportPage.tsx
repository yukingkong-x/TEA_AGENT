import { useEffect, useState } from 'react'
import { ConfidenceGauge } from '../components/ReportGauges'
import { Markdown } from '../components/Markdown'
import { PageFrame } from '../components/PageFrame'
import { ReportTrend } from '../components/ReportTrend'
import { dailyMarkdown, patrolRuns, type PatrolRound } from '../data/patrolReport'

export function ReportPage() {
  const [runId, setRunId] = useState(patrolRuns[0].id)
  const [daily, setDaily] = useState<string | null>(null)
  const run = patrolRuns.find((item) => item.id === runId) ?? patrolRuns[0]
  const latest = run.rounds[run.rounds.length - 1]

  return (
    <PageFrame title="验证报告">
      <div className="flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-3 text-sm text-dim" htmlFor="report-run">
            本次巡园
            <select
              id="report-run"
              value={run.id}
              onChange={(event) => {
                setRunId(event.target.value)
                setDaily(null)
              }}
              className="h-11 rounded-btn border border-line bg-panel px-3 text-base text-paper"
            >
              {patrolRuns.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <p className="text-sm text-mute">
            {run.outcome}。第 {latest.round} 轮复测 {latest.measured.toFixed(1)}%。
          </p>
        </div>

        <div className="grid items-stretch gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
          <section className="rounded-2xl bg-[#F7F8FA] px-4 py-4">
            <h2 className="text-center text-paper">置信度</h2>
            <ConfidenceGauge value={latest.confidence} caption={`第 ${latest.round} 轮`} />
          </section>
          <section className="min-w-0 rounded-2xl bg-[#F7F8FA] px-5 py-4">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-paper">湿度轨迹</h2>
              <p className="text-sm text-mute">浇水前到两轮复测</p>
            </div>
            {run.id === 'run-1001' ? <ReportTrend /> : <p className="grid h-[280px] place-items-center text-sm text-mute">这次只有一轮，没有两轮湿度轨迹。</p>}
          </section>
        </div>

        {run.rounds.map((round) => (
          <RoundBlock key={round.round} round={round} />
        ))}

        <section className="rounded-2xl bg-[#F7F8FA] px-5 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-paper">日报</h2>
            <div className="no-print flex gap-3">
              <button type="button" className="h-11 rounded-btn bg-tea px-4 text-base text-white hover:bg-teaHover active:bg-teaPress" onClick={() => setDaily(dailyMarkdown(run))}>
                生成日报
              </button>
              <button type="button" className="h-11 rounded-btn border border-line bg-panel px-4 text-base text-paper hover:border-tea hover:text-tea" onClick={() => window.print()}>
                导出 PDF
              </button>
            </div>
          </div>
          <div className="mt-4">
            {daily ? <Markdown source={daily} /> : <p className="text-sm text-mute">点生成日报后，这里出现报告正文。</p>}
          </div>
        </section>
      </div>
    </PageFrame>
  )
}

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

function RateRing({ rate, color }: { rate: number; color: string }) {
  const progress = useGrow()
  const radius = 72
  const stroke = 16
  const size = 188
  const center = size / 2
  const length = 2 * Math.PI * radius

  return (
    <div className="relative h-[188px] w-[188px] shrink-0" aria-label={`达成率 ${rate.toFixed(2)}%`}>
      <svg viewBox={`0 0 ${size} ${size}`} className="h-full w-full" aria-hidden="true">
        <circle cx={center} cy={center} r={radius} fill="none" stroke="#E7EEE9" strokeWidth={stroke} />
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${length * (rate / 100) * progress} ${length}`}
          transform={`rotate(-90 ${center} ${center})`}
        />
      </svg>
      <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
        <div>
          <span className="num block text-[28px] font-semibold leading-none text-paper">{(rate * progress).toFixed(2)}%</span>
          <span className="mt-1 block text-xs leading-none text-mute">达成率</span>
        </div>
      </div>
    </div>
  )
}

function RoundBlock({ round }: { round: PatrolRound }) {
  const handedOff = round.confidence < 60
  const closed = round.rate >= 60
  const result = handedOff ? '转人工' : closed ? '闭环' : '未达标'
  const resultClass = handedOff ? 'bg-[#F3E8FF] text-[#6D28D9]' : closed ? 'bg-panel2 text-tea' : 'bg-[#FFF4CC] text-[#8A6414]'
  const ringColor = handedOff ? '#6D28D9' : closed ? '#1F7A45' : '#E4B423'

  return (
    <section className="rounded-2xl bg-[#F7F8FA] px-5 py-5">
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-paper">第 {round.round} 轮</h2>
          <dl className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl bg-panel px-3 py-3">
              <dt className="text-xs leading-none text-mute">基线</dt>
              <dd className="num mt-1 text-base text-paper">{round.baseline.toFixed(1)}%</dd>
            </div>
            <div className="rounded-xl bg-panel px-3 py-3">
              <dt className="text-xs leading-none text-mute">复测</dt>
              <dd className="num mt-1 text-base text-paper">{round.measured.toFixed(1)}%</dd>
            </div>
          </dl>
          <div className="mt-3 overflow-hidden rounded-xl border border-line bg-panel">
            <table className="w-full border-collapse text-left text-sm leading-normal">
              <tbody>
                <tr>
                  <th className="w-24 border-b border-line bg-[#F7F8FA] px-3 py-2.5 text-left text-sm font-normal text-dim">诊断</th>
                  <td className="border-b border-line px-3 py-2.5 text-paper">{round.diagnosis}</td>
                </tr>
                <tr>
                  <th className="w-24 border-b border-line bg-[#F7F8FA] px-3 py-2.5 text-left text-sm font-normal text-dim">修正策略</th>
                  <td className="border-b border-line px-3 py-2.5 text-paper">{round.correction}</td>
                </tr>
                <tr>
                  <th className="w-24 bg-[#F7F8FA] px-3 py-2.5 text-left text-sm font-normal text-dim">结果</th>
                  <td className="px-3 py-2.5">
                    <span className={`inline-flex h-6 items-center rounded-btn px-2 text-xs leading-none ${resultClass}`}>{result}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <RateRing rate={round.rate} color={ringColor} />
      </div>
    </section>
  )
}
