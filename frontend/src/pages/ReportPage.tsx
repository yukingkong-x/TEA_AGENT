import { useEffect, useState } from 'react'
import { ConfidenceGauge } from '../components/ReportGauges'
import { Markdown } from '../components/Markdown'
import { PageFrame } from '../components/PageFrame'
import { ReportTrend } from '../components/ReportTrend'
import { dailyMarkdown, formatAchievement, patrolRuns, type PatrolRound } from '../data/patrolReport'
import { CONFIDENCE_WEIGHTS, NEEDS_HUMAN_THRESHOLD, pct, raw01, weightedConfidence } from '../lib/units'

/** 结果徽章：转人工 > 基线缺失 > 闭环/未达标 */
function roundResultLabel(handedOff: boolean, closed: boolean, missing: boolean) {
  if (handedOff) return '转人工'
  if (missing) return '基线缺失 · 算不出'
  return closed ? '闭环' : '未达标'
}

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
            {run.outcome}。第 {latest.round} 轮复测 {pct(latest.measured, 1)}，置信度 {pct(latest.confidence)}。
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

function RateRing({ rate, color, missing }: { rate: number; color: string; missing?: boolean }) {
  const progress = useGrow()
  const radius = 72
  const stroke = 16
  const size = 188
  const center = size / 2
  const length = 2 * Math.PI * radius
  // 基线缺失时环不填充、显示「算不出来」——不能画成 0%（0% 会被误读成「浇了没效果」）
  const filled = missing ? 0 : rate

  return (
    // rate 是 0-100（contract 第 10 节 achievement 量纲），别再 ×100
    <div className="relative h-[188px] w-[188px] shrink-0" aria-label={missing ? '达成率算不出来（基线缺失）' : `达成率 ${pct(rate)}`}>
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
          strokeDasharray={`${length * (filled / 100) * progress} ${length}`}
          transform={`rotate(-90 ${center} ${center})`}
        />
      </svg>
      <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
        <div>
          {missing ? (
            <span className="block text-base font-semibold leading-none text-mute">算不出来</span>
          ) : (
            <span className="num block text-[28px] font-semibold leading-none text-paper">{pct(rate * progress)}</span>
          )}
          <span className="mt-1 block text-xs leading-none text-mute">{missing ? '基线缺失' : '达成率'}</span>
        </div>
      </div>
    </div>
  )
}

function RoundBlock({ round }: { round: PatrolRound }) {
  // 置信度是 0-100，阈值 60 直接比，别拿 0.6 比
  const handedOff = round.confidence < NEEDS_HUMAN_THRESHOLD
  // 基线缺失时达成率「算不出来」，不能当成未达标/闭环来判
  const missing = Boolean(round.baselineMissing) || round.baseline === null
  const closed = !missing && round.rate >= 60
  const result = roundResultLabel(handedOff, closed, missing)
  const resultClass = handedOff
    ? 'bg-[#F3E8FF] text-[#6D28D9]'
    : missing
      ? 'bg-[#EEF1F4] text-[#5A6474]'
      : closed
        ? 'bg-panel2 text-tea'
        : 'bg-[#FFF4CC] text-[#8A6414]'
  const ringColor = handedOff ? '#6D28D9' : missing ? '#86909C' : closed ? '#1F7A45' : '#E4B423'

  return (
    <section className="rounded-2xl bg-[#F7F8FA] px-5 py-5">
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <h2 className="text-paper">第 {round.round} 轮</h2>
          <dl className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl bg-panel px-3 py-3">
              <dt className="text-xs leading-none text-mute">基线</dt>
              {/* baseline 可能为 null（传感器没给浇水前读数），显示「—」，别 ?? 0 */}
              <dd className="num mt-1 text-base text-paper">{pct(round.baseline, 1)}</dd>
            </div>
            <div className="rounded-xl bg-panel px-3 py-3">
              <dt className="text-xs leading-none text-mute">复测</dt>
              <dd className="num mt-1 text-base text-paper">{pct(round.measured, 1)}</dd>
            </div>
            <div className="rounded-xl bg-panel px-3 py-3">
              <dt className="text-xs leading-none text-mute">达成率</dt>
              <dd className="num mt-1 text-base text-paper">{formatAchievement(round)}</dd>
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
                  <th className="w-24 border-b border-line bg-[#F7F8FA] px-3 py-2.5 text-left text-sm font-normal text-dim">置信度构成</th>
                  <td className="border-b border-line px-3 py-2.5">
                    <ConfidenceBreakdown round={round} />
                  </td>
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
        <RateRing rate={round.rate} color={ringColor} missing={missing} />
      </div>
    </section>
  )
}

/**
 * 置信度构成：三路原始分是 0-1，总分是 0-100，分两列显示，中间用加权说明隔开。
 * 后端给的 confidence 与加权值理论一致（允许 0.1 的四舍五入差）。
 */
function ConfidenceBreakdown({ round }: { round: PatrolRound }) {
  const detail = round.detail
  const weighted = weightedConfidence(detail)
  const rows = [
    { key: 'data_quality', label: '数据质量', weight: CONFIDENCE_WEIGHTS.data_quality },
    { key: 'rule_cross', label: '规则交叉', weight: CONFIDENCE_WEIGHTS.rule_cross },
    { key: 'consistency', label: '一致性', weight: CONFIDENCE_WEIGHTS.consistency },
  ] as const

  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        {rows.map((row) => (
          <span key={row.key} className="inline-flex items-baseline gap-1.5">
            <span className="text-xs leading-none text-dim">{row.label}</span>
            <span className="num text-sm text-paper">{raw01(detail[row.key])}</span>
            <span className="num text-xs leading-none text-mute">×{row.weight}</span>
          </span>
        ))}
      </div>
      <p className="num mt-2 text-xs leading-normal text-mute">
        加权 {pct(weighted, 1)}（对应 confidence {pct(round.confidence)}，阈值 {NEEDS_HUMAN_THRESHOLD}）
      </p>
      {detail.reasons?.length ? (
        <ul className="mt-2 list-disc pl-4 text-sm leading-normal text-paper">
          {detail.reasons.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}
