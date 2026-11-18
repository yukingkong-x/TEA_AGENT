import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { endpoints } from '../api/endpoints'
import type { NodeRecordDto, VerificationRecordDto, WorkflowRunDto } from '../api/types'
import { formatClock } from '../data/tasks'

/**
 * 任务中心的「智能体调用 / 验证 / 报告」三个标签。
 *
 * 这三类在数据模型里从来不是任务单：智能体调用落在 run 的 node_records，
 * 验证落在 verification 表，报告落在 reports 表。以前这三个标签直接筛
 * tasks.type，永远筛不到东西，所以全是空白。这里各自接真实来源。
 */

function PanelShell({ note, children }: { note: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <p className="shrink-0 px-5 pt-3 text-xs leading-normal text-mute">{note}</p>
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <p className="px-5 py-16 text-center text-xs leading-normal text-mute">{text}</p>
}

/* ------------------------------ 智能体调用 ------------------------------ */

type CallRow = {
  key: string
  runId: number
  round: number
  name: string
  agent: string
  status: string
  duration: number
  tokens: number
  tools: string[]
}

const RUNS_TO_SCAN = 6

export function AgentCallPanel() {
  const [rows, setRows] = useState<CallRow[]>([])
  const [state, setState] = useState<'loading' | 'ok' | 'fail'>('loading')

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const page = await endpoints.runs(1, RUNS_TO_SCAN)
        const runs: WorkflowRunDto[] = page.items ?? []
        const details = await Promise.all(
          runs.map((run) =>
            endpoints
              .runNodes(run.id)
              .then((res) => ({ run, nodes: res.items ?? [] }))
              .catch(() => ({ run, nodes: [] as NodeRecordDto[] })),
          ),
        )
        if (!alive) return
        const flat: CallRow[] = []
        for (const { run, nodes } of details) {
          for (const node of nodes) {
            // 只收真正调用智能体的节点：agent_key 非空就是某个智能体在干活
            if (!node.agent_key) continue
            flat.push({
              key: `${run.id}-${node.node_id}-${node.round_no}`,
              runId: run.id,
              round: node.round_no ?? 1,
              name: node.name,
              agent: node.agent_key,
              status: node.status,
              duration: node.duration_ms ?? 0,
              tokens: (node.tokens_in ?? 0) + (node.tokens_out ?? 0),
              tools: (node.tool_calls ?? []).map((call) => call.name ?? 'tool').filter(Boolean),
            })
          }
        }
        flat.sort((a, b) => b.runId - a.runId)
        setRows(flat)
        setState('ok')
      } catch {
        if (alive) setState('fail')
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  return (
    <PanelShell note={`最近 ${RUNS_TO_SCAN} 次运行里每个智能体节点的执行记录（来源：/api/runs/{id}/nodes）`}>
      {state === 'loading' ? <Empty text="正在读取运行节点…" /> : null}
      {state === 'fail' ? <Empty text="运行节点接口没有响应，稍后刷新重试。" /> : null}
      {state === 'ok' && rows.length === 0 ? <Empty text="还没有带智能体节点的运行记录。" /> : null}
      {rows.length > 0 ? (
        <table className="data-table is-hoverable w-full min-w-[900px] text-left text-sm leading-normal">
          <thead className="sticky top-0 z-10 bg-white/85 text-dim backdrop-blur-md">
            <tr>
              <th className="px-5 py-3 font-normal">运行</th>
              <th className="px-4 py-3 font-normal">轮次</th>
              <th className="px-4 py-3 font-normal">智能体</th>
              <th className="px-4 py-3 font-normal">节点</th>
              <th className="px-4 py-3 font-normal">工具调用</th>
              <th className="px-4 py-3 font-normal">耗时</th>
              <th className="px-4 py-3 font-normal">Tokens</th>
              <th className="px-4 py-3 font-normal">状态</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <td className="num px-5 py-4 text-tea">#{row.runId}</td>
                <td className="num px-4 py-4 text-dim">{row.round}</td>
                <td className="num px-4 py-4 text-paper">{row.agent}</td>
                <td className="px-4 py-4 text-dim">{row.name}</td>
                <td className="px-4 py-4">
                  {row.tools.length ? (
                    <span className="num text-xs text-dim">{row.tools.join(' · ')}</span>
                  ) : (
                    <span className="text-xs text-mute">—</span>
                  )}
                </td>
                <td className="num px-4 py-4">{(row.duration / 1000).toFixed(row.duration < 10_000 ? 2 : 1)}s</td>
                <td className="num px-4 py-4 text-dim">{row.tokens || '—'}</td>
                <td className="px-4 py-4">
                  <span
                    className={`inline-flex h-6 items-center rounded-btn px-2 text-xs leading-none ${
                      row.status === 'done' ? 'bg-[#E5F6EA] text-[#1F7A3A]' : 'bg-[#FBF3E6] text-[#9A5B12]'
                    }`}
                  >
                    {row.status === 'done' ? '完成' : row.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </PanelShell>
  )
}

/* -------------------------------- 验证 -------------------------------- */

const CONCLUSION: Record<string, { label: string; className: string }> = {
  success: { label: '闭环', className: 'bg-[#E5F6EA] text-[#1F7A3A]' },
  failed: { label: '未达标', className: 'bg-[#FBF3E6] text-[#9A5B12]' },
  needs_human: { label: '转人工', className: 'bg-[#F3E8FF] text-[#6D28D9]' },
  unverified: { label: '未验证', className: 'bg-[#EEF1EF] text-[#5C675F]' },
}

function num(value: number | null, digit = 1) {
  return typeof value === 'number' ? value.toFixed(digit) : '—'
}

export function VerifyPanel() {
  const [rows, setRows] = useState<VerificationRecordDto[]>([])
  const [state, setState] = useState<'loading' | 'ok' | 'fail'>('loading')

  useEffect(() => {
    let alive = true
    endpoints
      .verifyList({ page: 1, page_size: 50 })
      .then((page) => {
        if (!alive) return
        setRows(page.items ?? [])
        setState('ok')
      })
      .catch(() => {
        if (alive) setState('fail')
      })
    return () => {
      alive = false
    }
  }, [])

  return (
    <PanelShell note="验证官的复测记录：基线 → 复测 → 达成率 / 置信度（来源：/api/verify）">
      {state === 'loading' ? <Empty text="正在读取验证记录…" /> : null}
      {state === 'fail' ? <Empty text="验证记录接口没有响应，稍后刷新重试。" /> : null}
      {state === 'ok' && rows.length === 0 ? <Empty text="还没有验证记录，先跑一次巡园。" /> : null}
      {rows.length > 0 ? (
        <table className="data-table is-hoverable w-full min-w-[900px] text-left text-sm leading-normal">
          <thead className="sticky top-0 z-10 bg-white/85 text-dim backdrop-blur-md">
            <tr>
              <th className="px-5 py-3 font-normal">时间</th>
              <th className="px-4 py-3 font-normal">运行</th>
              <th className="px-4 py-3 font-normal">任务号</th>
              <th className="px-4 py-3 font-normal">基线</th>
              <th className="px-4 py-3 font-normal">复测</th>
              <th className="px-4 py-3 font-normal">目标区间</th>
              <th className="px-4 py-3 font-normal">达成率</th>
              <th className="px-4 py-3 font-normal">置信度</th>
              <th className="px-4 py-3 font-normal">结论</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const tone = CONCLUSION[row.conclusion] ?? CONCLUSION.unverified
              return (
                <tr key={row.id}>
                  <td className="num px-5 py-4 text-dim">{row.created_at ? formatClock(row.created_at) : '—'}</td>
                  <td className="num px-4 py-4 text-tea">{row.run_id !== null ? `#${row.run_id}` : '—'}</td>
                  <td className="num px-4 py-4 text-dim">{row.task_no}</td>
                  <td className="num px-4 py-4">{num(row.baseline_value)}%</td>
                  <td className="num px-4 py-4">{num(row.measured_value)}%</td>
                  <td className="num px-4 py-4 text-dim">
                    {row.target_low !== null && row.target_high !== null ? `${row.target_low}–${row.target_high}%` : '—'}
                  </td>
                  <td className="num px-4 py-4">{num(row.achievement)}%</td>
                  <td className="num px-4 py-4 text-dim">{num(row.confidence)}</td>
                  <td className="px-4 py-4">
                    <span className={`inline-flex h-6 items-center rounded-btn px-2 text-xs leading-none ${tone.className}`}>
                      {tone.label}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : null}
    </PanelShell>
  )
}

/* -------------------------------- 报告 -------------------------------- */

type ReportRow = { id: number; run_id: number | null; report_type: string; created_at: string | null }

export function ReportPanel() {
  const [rows, setRows] = useState<ReportRow[]>([])
  const [state, setState] = useState<'loading' | 'ok' | 'fail'>('loading')

  useEffect(() => {
    let alive = true
    endpoints
      .reports({ page: 1, page_size: 50 })
      .then((page) => {
        if (!alive) return
        setRows((page.items ?? []) as unknown as ReportRow[])
        setState('ok')
      })
      .catch(() => {
        if (alive) setState('fail')
      })
    return () => {
      alive = false
    }
  }, [])

  return (
    <PanelShell note="每次运行生成的巡园报告（来源：/api/reports），点右侧进入报告页看全文">
      {state === 'loading' ? <Empty text="正在读取报告列表…" /> : null}
      {state === 'fail' ? <Empty text="报告接口没有响应，稍后刷新重试。" /> : null}
      {state === 'ok' && rows.length === 0 ? <Empty text="还没有报告，运行结束后到报告页点「生成报告」。" /> : null}
      {rows.length > 0 ? (
        <table className="data-table is-hoverable w-full min-w-[720px] text-left text-sm leading-normal">
          <thead className="sticky top-0 z-10 bg-white/85 text-dim backdrop-blur-md">
            <tr>
              <th className="px-5 py-3 font-normal">报告号</th>
              <th className="px-4 py-3 font-normal">运行</th>
              <th className="px-4 py-3 font-normal">类型</th>
              <th className="px-4 py-3 font-normal">生成时间</th>
              <th className="px-4 py-3 font-normal">操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <td className="num px-5 py-4 text-tea">R-{row.id}</td>
                <td className="num px-4 py-4 text-dim">{row.run_id !== null ? `#${row.run_id}` : '—'}</td>
                <td className="px-4 py-4">{row.report_type === 'run' ? '运行报告' : row.report_type}</td>
                <td className="num px-4 py-4 text-dim">{row.created_at ? formatClock(row.created_at) : '—'}</td>
                <td className="px-4 py-4">
                  <Link to="/report" className="text-tea hover:underline">
                    打开报告页
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </PanelShell>
  )
}
