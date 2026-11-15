import { useCallback, useEffect, useRef, useState } from 'react'
import { endpoints } from '../api/endpoints'
import type { NodeRecordDto, NodeSummaryDto, RunRoundsDto, WorkflowRunDto } from '../api/types'
import { ConfidenceGauge } from '../components/ReportGauges'
import { Markdown } from '../components/Markdown'
import { PageFrame } from '../components/PageFrame'
import { ReportTrend } from '../components/ReportTrend'
import {
  dailyMarkdown,
  formatAchievement,
  formatDuration,
  outcomeLabel,
  patrolRuns,
  runFromApi,
  type PatrolRound,
  type PatrolRun,
  type RunOutcome,
} from '../data/patrolReport'
import { CONFIDENCE_WEIGHTS, NEEDS_HUMAN_THRESHOLD, pct, raw01, weightedConfidence } from '../lib/units'

/** 结果徽章：转人工 > 基线缺失 > 闭环/未达标 */
function roundResultLabel(handedOff: boolean, closed: boolean, missing: boolean) {
  if (handedOff) return '转人工'
  if (missing) return '基线缺失 · 算不出'
  return closed ? '闭环' : '未达标'
}

/** 真实 run 的选项前缀；样例带前缀是为了和 `run-1001` 这类假 id 区分开 */
const REAL = 'real:'
const SAMPLE = 'sample:'

export function ReportPage() {
  /** 后端真实的执行实例（有几次巡园就有几条） */
  const [realRuns, setRealRuns] = useState<WorkflowRunDto[]>([])
  const [selected, setSelected] = useState<string>(`${SAMPLE}${patrolRuns[0].id}`)
  const [view, setView] = useState<RunRoundsDto | null>(null)
  const [nodes, setNodes] = useState<NodeRecordDto[]>([])
  const [nodeSummary, setNodeSummary] = useState<NodeSummaryDto | null>(null)
  const [daily, setDaily] = useState<string | null>(null)
  const [dailyNote, setDailyNote] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  /** 用户是否亲手选过（选过就不再被「最新真实 run」抢走） */
  const touched = useRef(false)

  // 真实 run 列表：拿到就把选中项切到最新一条真实执行上（演示时打开就是真数据）
  // 但只在用户还没动过选择器时才切——否则「先选了样例/旧 run，列表后到」会被抢回最新一条
  useEffect(() => {
    let alive = true
    endpoints
      .runs(1, 50)
      .then((page) => {
        if (!alive) return
        const items = page.items ?? []
        setRealRuns(items)
        if (items.length > 0 && !touched.current) setSelected(`${REAL}${items[0].id}`)
      })
      .catch(() => {
        // 接口挂了就老实用样例，页面不能白屏
      })
    return () => {
      alive = false
    }
  }, [])

  const runId = selected.startsWith(REAL) ? Number(selected.slice(REAL.length)) : null

  // 轮次与节点耗时：同一个 run 的两份数据一起拉，页面上「第几轮」和「哪段慢」能对上
  useEffect(() => {
    if (runId === null) {
      setView(null)
      setNodes([])
      setNodeSummary(null)
      return
    }
    let alive = true
    setLoading(true)
    Promise.all([endpoints.runRounds(runId), endpoints.runNodes(runId).catch(() => null)])
      .then(([rounds, nodePage]) => {
        if (!alive) return
        setView(rounds)
        setNodes(nodePage?.items ?? [])
        setNodeSummary(nodePage?.summary ?? null)
        setError('')
      })
      .catch((err) => {
        if (!alive) return
        setError(err instanceof Error ? err.message : String(err))
        setView(null)
      })
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [runId])

  const isReal = runId !== null
  const sampleRun = patrolRuns.find((item) => `${SAMPLE}${item.id}` === selected) ?? patrolRuns[0]
  // 真实数据到了就用真实数据；接口失败时退回样例，并在页面上标明「这是样例」
  const run: PatrolRun = isReal && view ? runFromApi(view) : sampleRun
  const latest = run.rounds.length ? run.rounds[run.rounds.length - 1] : null

  /** 真实 run 的日报取后端生成的那份 Markdown（与导出 PDF 同源），样例走本地拼装 */
  const makeDaily = useCallback(async () => {
    if (!isReal) {
      setDailyNote('样例数据（后端无该执行实例）')
      setDaily(dailyMarkdown(run))
      return
    }
    try {
      // 先找已生成的报告，避免每次点都往 reports 表插一条
      const existing = await endpoints.reports({ run_id: runId as number, report_type: 'run', page: 1, page_size: 1 })
      const hit = existing.items[0] as { id: number } | undefined
      const reportId = hit?.id ?? (await endpoints.generateReport(runId as number)).report_id
      const detail = (await endpoints.report(reportId)) as { content_md?: string }
      setDailyNote(`后端报告 #${reportId}（与导出 PDF 同源）`)
      setDaily(detail.content_md ?? dailyMarkdown(run))
    } catch (err) {
      setDailyNote('后端报告生成失败，下面这份是页面按当前轮次拼的')
      setDaily(dailyMarkdown(run))
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [isReal, run, runId])

  return (
    <PageFrame title="验证报告">
      <div className="flex flex-col gap-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-3 text-sm text-dim" htmlFor="report-run">
            本次巡园
            <select
              id="report-run"
              value={selected}
              onChange={(event) => {
                touched.current = true
                setSelected(event.target.value)
                setDaily(null)
                setDailyNote('')
              }}
              className="h-11 rounded-btn border border-line bg-panel px-3 text-base text-paper"
            >
              {realRuns.length > 0 ? (
                <optgroup label="真实执行">
                  {realRuns.map((item) => (
                    <option key={item.id} value={`${REAL}${item.id}`}>
                      #{item.id} · {item.started_at?.replace('T', ' ').slice(5, 16) ?? '未开始'} · {item.status}
                    </option>
                  ))}
                </optgroup>
              ) : null}
              <optgroup label={realRuns.length > 0 ? '样例数据（演示用，非真实执行）' : '样例数据'}>
                {patrolRuns.map((item) => (
                  <option key={item.id} value={`${SAMPLE}${item.id}`}>
                    {item.name}
                  </option>
                ))}
              </optgroup>
            </select>
          </label>
          <p className="text-sm text-mute">
            <span className="text-paper">{outcomeLabel(run.outcome)}</span>
            {latest
              ? `。第 ${latest.round} 轮复测 ${pct(latest.measured, 1)}，置信度 ${pct(latest.confidence)}。`
              : '。这次没有验证记录，不判定是否达标。'}
          </p>
        </div>

        {loading ? <p className="text-sm text-mute">正在读取这次执行的验证记录…</p> : null}
        {error ? (
          <p className="rounded-btn bg-[#FFF4CC] px-3 py-2 text-sm text-[#8A6414]">
            读取失败：{error}
          </p>
        ) : null}
        {isReal && !view && !loading ? (
          <p className="text-sm text-mute">
            这次执行还没有轮次数据（验证官未出记录，或 run 还没跑完），下面按「未产生验证结果」处理。
          </p>
        ) : null}

        {run.outcome === 'needs_human' ? (
          // 转人工不是失败：系统已经停手，不会自动重试、不会再下发设备指令
          <section className="rounded-2xl border border-[#DCCBFF] bg-[#F7F2FF] px-5 py-4">
            <h2 className="text-paper">🚨 已转人工，系统不再自动重试</h2>
            <p className="mt-2 max-w-[64ch] text-sm leading-relaxed text-dim">
              置信度低于 60% 或 Self-Loop 轮次已用完，系统已停在最后一轮。这里<strong className="font-semibold text-paper">不会</strong>再排修正任务、不会再下发浇水指令，也不按「失败」重跑——请人工核对传感器读数与设备状态，确认后手动复测。
            </p>
          </section>
        ) : null}

        {latest ? (
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
              {run.rounds.length >= 2 ? (
                <ReportTrend rounds={run.rounds} />
              ) : (
                <p className="grid h-[280px] place-items-center text-sm text-mute">这次只有一轮，没有两轮湿度轨迹。</p>
              )}
            </section>
          </div>
        ) : (
          // outcome=unverified：run 收尾了但验证官没出记录，页面不画空圆环、不写 0%
          <section className="rounded-2xl border border-[#E8D9A8] bg-[#FFF9E8] px-5 py-6">
            <h2 className="text-paper">⚠️ 未产生验证结果</h2>
            <p className="mt-2 max-w-[64ch] text-sm leading-relaxed text-dim">
              这次运行已经结束，但没有任何验证记录，所以没有基线 / 复测读数，也算不出达成率与置信度。流程跑通不等于浇水达标，这里不写「闭环成功」，也不画 0% 的绿环。
            </p>
            <p className="mt-2 max-w-[64ch] text-sm leading-normal text-mute">
              常见原因：本轮决策为暂不作业（走归档分支）、设备回执未完成或熔断导致没有复测读数、渗透期不足 90 秒。
            </p>
          </section>
        )}

        {run.rounds.map((round, index) => (
          // round_no 由后端任务载荷决定，两轮理论上不会重号，但补 index 兜底
          <RoundBlock
            key={`${round.round}-${index}`}
            round={round}
            isFinal={index === run.rounds.length - 1}
            runOutcome={run.outcome}
          />
        ))}

        <NodeTimeline nodes={nodes} summary={nodeSummary} />

        <section className="rounded-2xl bg-[#F7F8FA] px-5 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-paper">日报</h2>
            <div className="no-print flex gap-3">
              <button type="button" className="h-11 rounded-btn bg-tea px-4 text-base text-white hover:bg-teaHover active:bg-teaPress" onClick={() => void makeDaily()}>
                生成日报
              </button>
              <button type="button" className="h-11 rounded-btn border border-line bg-panel px-4 text-base text-paper hover:border-tea hover:text-tea" onClick={() => window.print()}>
                导出 PDF
              </button>
            </div>
          </div>
          <div className="mt-4">
            {daily ? (
              <>
                {dailyNote ? <p className="mb-2 text-xs leading-normal text-mute">来源：{dailyNote}</p> : null}
                <Markdown source={daily} />
              </>
            ) : (
              <p className="text-sm text-mute">点生成日报后，这里出现报告正文。</p>
            )}
          </div>
        </section>
      </div>
    </PageFrame>
  )
}

/**
 * 节点耗时（B 的 workflow_node_records）。
 * items 为空 = 这次 run 没有节点明细（引擎接表之前的历史 run），整段不渲染——
 * 别显示「加载失败」，那不是错误，只是没这层数据。
 */
function NodeTimeline({ nodes, summary }: { nodes: NodeRecordDto[]; summary: NodeSummaryDto | null }) {
  if (!nodes.length) return null
  const rounds = [...new Set(nodes.map((node) => node.round_no || 1))].sort((a, b) => a - b)
  return (
    <section className="rounded-2xl bg-[#F7F8FA] px-5 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-paper">节点耗时</h2>
        {summary ? (
          <p className="num text-sm text-mute">
            {summary.node_count} 个节点 · 共 {(summary.duration_ms / 1000).toFixed(1)}s
            {summary.slowest ? ` · 最慢 ${summary.slowest.name} ${(summary.slowest.duration_ms / 1000).toFixed(1)}s` : ''}
            {summary.loop ? ` · Self-Loop 阶段 ${(summary.loop.duration_ms / 1000).toFixed(1)}s` : ''}
            {summary.degraded_count ? ` · 降级 ${summary.degraded_count}` : ''}
            {summary.failed_count ? ` · 失败 ${summary.failed_count}` : ''}
          </p>
        ) : null}
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm leading-normal">
          <thead>
            <tr className="text-xs text-mute">
              <th className="border-b border-line px-3 py-2 text-left font-normal">节点</th>
              <th className="border-b border-line px-3 py-2 text-left font-normal">轮次</th>
              <th className="border-b border-line px-3 py-2 text-left font-normal">耗时</th>
              <th className="border-b border-line px-3 py-2 text-left font-normal">工具</th>
              <th className="border-b border-line px-3 py-2 text-left font-normal">状态</th>
            </tr>
          </thead>
          <tbody>
            {nodes.map((node) => (
              <tr key={`${node.node_id}-${node.round_no}`}>
                <td className="border-b border-line px-3 py-2 text-paper">
                  <span className="num mr-2 text-xs text-mute">{node.node_id}</span>
                  {node.name}
                  {node.node_type === 'loop' ? <span className="ml-2 text-xs text-mute">（含整个修正轮）</span> : null}
                </td>
                <td className="num border-b border-line px-3 py-2 text-dim">
                  {rounds.length > 1 ? `第 ${node.round_no || 1} 轮` : '—'}
                </td>
                <td className="num border-b border-line px-3 py-2 text-paper">{(node.duration_ms / 1000).toFixed(1)}s</td>
                <td className="num border-b border-line px-3 py-2 text-dim">{node.tool_calls?.length || '—'}</td>
                <td className="border-b border-line px-3 py-2">
                  <span
                    className={`inline-flex h-6 items-center rounded-btn px-2 text-xs leading-none ${
                      node.status === 'failed'
                        ? 'bg-[#FFECEC] text-[#B42318]'
                        : node.status === 'done'
                          ? 'bg-panel2 text-tea'
                          : 'bg-[#EEF1F4] text-[#5A6474]'
                    }`}
                  >
                    {node.status}
                  </span>
                  {node.degraded ? <span className="ml-2 text-xs text-[#8A6414]">降级</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
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

function RoundBlock({
  round,
  isFinal,
  runOutcome,
}: {
  round: PatrolRound
  isFinal?: boolean
  runOutcome?: RunOutcome
}) {
  // 置信度是 0-100，阈值 60 直接比，别拿 0.6 比
  // 整体转人工时最后一轮也标「转人工」：否则整页写转人工、这一行却写「未达标」，自相矛盾
  const handedOff =
    round.confidence < NEEDS_HUMAN_THRESHOLD || (Boolean(isFinal) && runOutcome === 'needs_human')
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
          <dl className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
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
            <div className="rounded-xl bg-panel px-3 py-3">
              {/* duration_s 是真值（后端按 task_no 回查任务载荷）；没查到显示「—」，不写 0 秒 */}
              <dt className="text-xs leading-none text-mute">浇水时长</dt>
              <dd className="num mt-1 text-base text-paper">{formatDuration(round)}</dd>
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
