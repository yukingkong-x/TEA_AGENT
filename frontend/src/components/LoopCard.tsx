/**
 * 最近一次闭环（总控页右下）—— 把「巡园 → 会诊 → 决策 → 执行 → 验证」这条链
 * 在总控页直接摊开，替掉原来那张和传感面板重复的「土壤湿度」曲线卡。
 *
 * 数据来源（全部真实，不造数）：
 * - GET /api/runs?page=1&page_size=1     最近一次执行实例（status / context / 时间）
 * - GET /api/runs/{id}                  该次执行下发的任务（执行端 + 指令 + 状态）
 * - GET /api/verify                     该任务的验证记录（基线 / 复测 / 达成率 / 置信度）
 *
 * 三态口径与报告页/任务中心保持一致：
 * - run.status = success         → 闭环
 * - needs_human（自循环用完）     → 转人工，绝不写成「闭环成功」
 * - failed                       → 未达标
 * - 没有验证记录                  → 只显示「待验证」，不宣称达成
 * 卡片自己 20s 轮询一次；脱离 WS 也能自洽（用户录视频时不管开哪页都在这刷）。
 */
import { useEffect, useState } from 'react'
import { endpoints } from '../api/endpoints'
import type { TaskDto, VerificationRecordDto, WorkflowRunDto } from '../api/types'
import { GlassCard } from './GlassCard'

type LoopStep = {
  key: string
  label: string
  /** 该环节的判读文字（真实字段截取，没有就写缺什么） */
  text: string
  state: 'done' | 'warn' | 'idle' | 'run'
}

type Snapshot = {
  run: WorkflowRunDto
  task: TaskDto | null
  verify: VerificationRecordDto | null
}

const ACTION_LABEL: Record<string, string> = {
  pump: '水泵',
  valve: '电磁阀',
  light: '补光',
  fan: '风机',
}

const TASK_STATE: Record<string, { text: string; state: LoopStep['state'] }> = {
  done: { text: '已回执', state: 'done' },
  success: { text: '已回执', state: 'done' },
  retrying: { text: '重试中', state: 'warn' },
  failed: { text: '执行失败', state: 'warn' },
  pending: { text: '待执行', state: 'run' },
  running: { text: '执行中', state: 'run' },
  timeout: { text: '执行超时', state: 'warn' },
}

function verdictOf(status: string): { text: string; tone: 'ok' | 'warn' | 'bad' | 'run' } {
  if (status === 'success') return { text: '闭环', tone: 'ok' }
  if (status === 'needs_human') return { text: '转人工', tone: 'warn' }
  if (status === 'failed') return { text: '未达标', tone: 'bad' }
  if (status === 'running') return { text: '进行中', tone: 'run' }
  return { text: status || '未知', tone: 'run' }
}

/** 截到 n 个字，去掉 markdown 标题碎屑，保留一句人话 */
function clip(raw: unknown, n = 46): string {
  if (typeof raw !== 'string') return ''
  const flat = raw
    .replace(/[#*`]/g, '')
    .replace(/【[^】]{1,8}】/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return flat.length > n ? `${flat.slice(0, n)}…` : flat
}

function clockOf(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function LoopCard() {
  const [data, setData] = useState<Snapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    const pull = async () => {
      try {
        const page = await endpoints.runs(1, 1)
        const run = page.items[0]
        if (!run) {
          if (alive) {
            setData(null)
            setFailed(false)
          }
          return
        }
        const [detail, verifies] = await Promise.all([
          endpoints.run(run.id),
          endpoints.verifyList({ page: 1, page_size: 30 }),
        ])
        const task = detail.tasks?.[0] ?? null
        const verify =
          verifies.items.find((item) => item.task_no === task?.task_no) ??
          verifies.items.find((item) => item.run_id === run.id) ??
          null
        if (alive) {
          setData({ run, task, verify })
          setFailed(false)
        }
      } catch {
        if (alive) setFailed(true)
      } finally {
        if (alive) setLoading(false)
      }
    }
    void pull()
    const timer = window.setInterval(() => void pull(), 20_000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [])

  const ctx = (data?.run.context ?? {}) as Record<string, unknown>
  const round = typeof ctx.round === 'number' ? ctx.round : null
  const verdict = data ? verdictOf(data.run.status) : null
  const task = data?.task ?? null
  const verify = data?.verify ?? null
  const payload = (task?.payload ?? {}) as Record<string, unknown>
  const params = (payload.params ?? {}) as Record<string, unknown>
  const action = typeof payload.action === 'string' ? payload.action : ''
  const duration = typeof params.duration_s === 'number' ? params.duration_s : null
  const taskState = task ? (TASK_STATE[String(task.status)] ?? { text: String(task.status), state: 'run' as const }) : null

  const steps: LoopStep[] = data
    ? [
        {
          key: 'scout',
          label: '巡园',
          text: clip(ctx.scout) || '这次执行没有留下巡园播报',
          state: ctx.scout ? 'done' : 'idle',
        },
        {
          key: 'consult',
          label: '会诊',
          text:
            [ctx.soil && '墒情', ctx.weather && '气象', ctx.pest && '植保'].filter(Boolean).join(' / ') +
              (ctx.soil ? ` · ${clip(ctx.soil, 34)}` : ' · 三方评估缺失'),
          state: ctx.soil && ctx.weather ? 'done' : 'warn',
        },
        {
          key: 'decision',
          label: '决策',
          text: clip(ctx.decision, 40) || '没有决策记录',
          state: ctx.decision ? 'done' : 'idle',
        },
        {
          key: 'exec',
          label: '执行',
          text: task
            ? `${ACTION_LABEL[action] ?? (action || '指令')}${duration ? ` ${duration}s` : ''} · ${task.assigned_device ?? '未指定执行端'} · ${taskState?.text}`
            : '本轮没有下发任务',
          state: taskState?.state ?? 'idle',
        },
        {
          key: 'verify',
          label: '验证',
          text: verify
            ? `基线 ${fmt(verify.baseline_value)}% → 复测 ${fmt(verify.measured_value)}% · 达成 ${fmt(verify.achievement, 0)}% · 置信 ${fmt(verify.confidence, 0)}%`
            : '没有验证记录——流程跑通不等于达标，不宣称闭环',
          state: verify ? (verify.conclusion === 'success' ? 'done' : 'warn') : 'idle',
        },
      ]
    : []

  return (
    <GlassCard className="flex min-h-[360px] flex-col xl:col-span-2" tilt={false} label="最近一次闭环">
      <div className="flex items-start justify-between gap-2 px-5 pt-4">
        <div>
          <h2 className="text-paper">最近一次闭环</h2>
          <p className="mt-1 text-sm text-mute">
            {data
              ? `${clockOf(data.run.started_at ?? data.run.created_at)}${round ? ` · 第 ${round} 轮` : ''}${
                  data.run.trigger === 'manual' ? ' · 手动触发' : ''
                }`
              : loading
                ? '读取执行记录…'
                : failed
                  ? '执行记录读取失败'
                  : '还没有执行记录'}
          </p>
        </div>
        {verdict ? (
          <span
            className={`shrink-0 rounded-btn px-2 py-1 text-xs leading-none ${
              verdict.tone === 'ok'
                ? 'bg-[#E8F5EC] text-[#1F7A45]'
                : verdict.tone === 'warn'
                  ? 'bg-[#FFF4CC] text-[#6E5314]'
                  : verdict.tone === 'bad'
                    ? 'bg-[#FDECEA] text-[#C0392B]'
                    : 'bg-[#F2F3F5] text-[#86909C]'
            }`}
          >
            {verdict.text}
          </span>
        ) : null}
      </div>

      <div className="mt-3 flex-1 px-5 pb-4">
        {steps.length ? (
          <ol className="flex flex-col">
            {steps.map((step, index) => (
              <li key={step.key} className="flex gap-3">
                <div className="flex w-3 shrink-0 flex-col items-center">
                  <span
                    className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                      step.state === 'done'
                        ? 'bg-[#1F7A45]'
                        : step.state === 'warn'
                          ? 'bg-[#E4B423]'
                          : step.state === 'run'
                            ? 'bg-[#7FB2D9]'
                            : 'bg-[#D5DBE1]'
                    }`}
                  />
                  {index < steps.length - 1 ? <span className="mt-1 w-px flex-1 bg-[#E6EBE7]" /> : null}
                </div>
                <div className="min-w-0 pb-3">
                  <p className="text-[11px] leading-none text-mute">{step.label}</p>
                  <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-paper">{step.text}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-xs leading-relaxed text-mute">
            {loading ? '正在读取最近一次巡园浇水记录…' : '还没有跑过闭环。去对话页发起一次巡园，这条链会在这里逐段点亮。'}
          </p>
        )}
        {typeof ctx.error === 'string' && ctx.error ? (
          <p className="mt-1 rounded-btn bg-[#FFF8E6] px-2.5 py-2 text-[11px] leading-relaxed text-[#6E5314]">
            {ctx.error}
          </p>
        ) : null}
      </div>
    </GlassCard>
  )
}

function fmt(value: number | null | undefined, digits = 1): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}
