/**
 * 任务状态机与徽章 —— 以 `docs/contracts/agent-data-contract.md` 第 3 节为准。
 *
 * 十个值：pending / dispatched / running / success / failed / timeout / retrying / dead / needs_human / canceled。
 * 没有 queued（就是 pending）、没有 completed（就是 success）、没有 waiting_tool / tool_done；
 * `degraded` 不是任务状态，是 Agent 消息上的降级标记（第 5 节），别混进来。
 */

export type TaskStatus =
  | 'pending'
  | 'dispatched'
  | 'running'
  | 'success'
  | 'failed'
  | 'timeout'
  | 'retrying'
  | 'dead'
  | 'needs_human'
  | 'canceled'

/** task_status 事件的 reason 全集（第 9 节）：只用于排查，不要按它分支渲染 */
export type TaskReason =
  | 'dispatch'
  | 'timeout'
  | 'retry_armed'
  | 'retry_due'
  | 'retry_hold_offline'
  | 'retries_exhausted'
  | 'breaker_open'
  | 'rejected_breaker_open'
  | (string & {})

/**
 * 轨迹的一步 = 状态机的一条边 `from → to`，直接来自 task_status 事件，前端不自己推。
 * `from === to === 'retrying'` 是 retry_hold_offline：挂着等设备，不是重试失败。
 */
export type TaskTrace = {
  from: TaskStatus | null
  to: TaskStatus
  at: string
  reason?: TaskReason
  /** 事件里额外带的信息，如「剩余 12s」 */
  note?: string
  /**
   * 事件种类（contract / 队长 11.14）：
   * - `status` 调度器的 task_status，画实线圆点
   * - `verify` 验证那一跳（from=任务原状态、to=结论、reason=verdict），单独画虚线
   */
  kind?: 'status' | 'verify'
  /** 谁干的：scheduler / device / verifier / human */
  actor?: string
}

export type TaskResult = {
  /** 熔断拒绝：`breaker_open` */
  rejected?: string
  /** 熔断拒绝时的剩余冷却秒数 */
  retry_after_s?: number
  /** 验证结论：success / failed / needs_human（needs_human 枚举补齐前会落 failed + 这里） */
  verdict?: string
  [key: string]: unknown
}

export type TaskRow = {
  id: string
  type: 'agent_call' | 'device_cmd' | 'verify' | 'report' | 'selfloop'
  target: string
  priority: number
  score: number | null
  status: TaskStatus
  retry_count: number
  elapsed: string
  created: string
  run_id?: number | null
  assigned_agent?: string | null
  assigned_device?: string | null
  result?: TaskResult | null
  trace: TaskTrace[]
}

export const taskStatusMeta: Record<TaskStatus, { label: string; className: string }> = {
  pending: { label: '排队', className: 'bg-[#EEF1EF] text-[#5C675F]' },
  dispatched: { label: '已派发', className: 'bg-[#E8F0FE] text-[#1D4ED8]' },
  running: { label: '执行中', className: 'bg-[#E7F0FA] text-[#1D4ED8] badge-flash' },
  success: { label: '成功', className: 'bg-[#E5F6EA] text-[#1F7A3A]' },
  failed: { label: '失败', className: 'bg-[#FDECEC] text-[#B42318]' },
  timeout: { label: '超时', className: 'bg-[#FDECEC] text-[#C2410C]' },
  retrying: { label: '重试', className: 'bg-[#FBF3E6] text-[#9A5B12]' },
  dead: { label: '熔断/耗尽', className: 'bg-[#3F1212] text-[#F8D0D0]' },
  needs_human: { label: '转人工', className: 'bg-[#F3E8FF] text-[#6D28D9]' },
  canceled: { label: '已取消', className: 'bg-[#EEF1EF] text-[#5C675F]' },
}

/**
 * 徽章判定：先看 result，再落到 status。
 * - 熔断拒绝落 `dead` + `result.rejected = "breaker_open"` → 「熔断拒绝 · 剩余 Ns」
 * - `needs_human` 枚举补齐前会以 `failed` + `result.verdict = "needs_human"` 出现 → 走紫色转人工
 */
export function badgeFor(task: Pick<TaskRow, 'status' | 'result'>): { label: string; className: string } {
  if (task.result?.rejected === 'breaker_open') {
    const wait = typeof task.result.retry_after_s === 'number' ? ` · 剩余 ${task.result.retry_after_s}s` : ''
    return { label: `熔断拒绝${wait}`, className: taskStatusMeta.dead.className }
  }
  if (task.status === 'failed' && task.result?.verdict === 'needs_human') {
    return taskStatusMeta.needs_human
  }
  return taskStatusMeta[task.status]
}

/** retry_hold_offline：事件里 from == to == retrying，挂设备期间不该重复播重试动画 */
export function isHoldOffline(step: TaskTrace): boolean {
  return step.from === 'retrying' && step.to === 'retrying'
}

const day = '2026-11-14'

function at(clock: string) {
  return `${day}T${clock}+08:00`
}

function step(from: TaskStatus | null, to: TaskStatus, clock: string, extra: Partial<TaskTrace> = {}): TaskTrace {
  return { from, to, at: at(clock), ...extra }
}

export const tasks: TaskRow[] = [
  {
    id: 'task-20261114-0007',
    type: 'device_cmd',
    target: 'k10-act-03 浇水 30 秒',
    priority: 6,
    score: 0.71,
    status: 'running',
    retry_count: 0,
    elapsed: '进行中',
    created: at('21:06:01'),
    assigned_agent: 'executor',
    assigned_device: 'k10-act-03',
    trace: [
      step(null, 'pending', '21:06:01'),
      step('pending', 'dispatched', '21:06:02', { reason: 'dispatch' }),
      step('dispatched', 'running', '21:06:03'),
    ],
  },
  {
    id: 'task-20261114-0008',
    type: 'verify',
    target: 'esp32-soil-02 复测',
    priority: 8,
    score: 0.77,
    status: 'dispatched',
    retry_count: 0,
    elapsed: '1 秒',
    created: at('21:07:40'),
    assigned_agent: 'verifier',
    trace: [step(null, 'pending', '21:07:40'), step('pending', 'dispatched', '21:07:41', { reason: 'dispatch' })],
  },
  {
    id: 'task-20261114-0009',
    type: 'device_cmd',
    target: 'k10-field-01 补测环境',
    priority: 4,
    score: null,
    status: 'pending',
    retry_count: 0,
    elapsed: '—',
    created: at('21:08:12'),
    trace: [step(null, 'pending', '21:08:12')],
  },
  {
    // retry_hold_offline：设备离线时一直挂在 retrying，from == to，不重复播重试动画
    id: 'task-20261114-0006',
    type: 'device_cmd',
    target: 'k10-act-03 浇水 30 秒',
    priority: 6,
    score: 0.59,
    status: 'retrying',
    retry_count: 1,
    elapsed: '8 秒',
    created: at('20:41:02'),
    assigned_device: 'k10-act-03',
    trace: [
      step(null, 'pending', '20:41:02'),
      step('pending', 'dispatched', '20:41:03', { reason: 'dispatch' }),
      step('dispatched', 'running', '20:41:04'),
      step('running', 'timeout', '20:41:10', { reason: 'timeout_6s' }),
      step('timeout', 'retrying', '20:41:10', { reason: 'retry_armed' }),
      step('retrying', 'retrying', '20:41:12', { reason: 'retry_hold_offline' }),
      step('retrying', 'retrying', '20:41:24', { reason: 'retry_hold_offline' }),
    ],
  },
  {
    // 熔断拒绝：落 dead，但徽章要显示「熔断拒绝 · 剩余 Ns」
    id: 'task-20261114-0005',
    type: 'device_cmd',
    target: 'k10-act-03 浇水 30 秒',
    priority: 6,
    score: 0.55,
    status: 'dead',
    retry_count: 0,
    elapsed: '2 秒',
    created: at('20:39:10'),
    assigned_device: 'k10-act-03',
    result: { rejected: 'breaker_open', retry_after_s: 12 },
    trace: [
      step(null, 'pending', '20:39:10'),
      step('pending', 'dispatched', '20:39:11', { reason: 'dispatch' }),
      step('dispatched', 'dead', '20:39:12', { reason: 'rejected_breaker_open', note: '熔断打开，剩余 12s' }),
    ],
  },
  {
    // 重试耗尽
    id: 'task-20261114-0004',
    type: 'device_cmd',
    target: 'k10-act-03 浇水 30 秒',
    priority: 6,
    score: 0.49,
    status: 'dead',
    retry_count: 3,
    elapsed: '26 秒',
    created: at('20:44:01'),
    assigned_device: 'k10-act-03',
    trace: [
      step(null, 'pending', '20:44:01'),
      step('pending', 'dispatched', '20:44:02', { reason: 'dispatch' }),
      step('dispatched', 'running', '20:44:03'),
      step('running', 'timeout', '20:44:09', { reason: 'timeout_6s' }),
      step('timeout', 'retrying', '20:44:09', { reason: 'retry_armed' }),
      step('retrying', 'running', '20:44:13', { reason: 'retry_due' }),
      step('running', 'timeout', '20:44:19', { reason: 'timeout_6s' }),
      step('timeout', 'retrying', '20:44:19', { reason: 'retry_armed' }),
      step('retrying', 'dead', '20:44:27', { reason: 'retries_exhausted' }),
    ],
  },
  {
    id: 'task-20261114-0003',
    type: 'agent_call',
    target: 'scout 巡园管家',
    priority: 7,
    score: 0.73,
    status: 'success',
    retry_count: 0,
    elapsed: '1 秒',
    created: at('21:02:18'),
    assigned_agent: 'scout',
    trace: [
      step(null, 'pending', '21:02:18'),
      step('pending', 'dispatched', '21:02:18', { reason: 'dispatch' }),
      step('dispatched', 'running', '21:02:19'),
      step('running', 'success', '21:02:19'),
    ],
  },
  {
    // needs_human 枚举补齐前：落 failed + result.verdict，徽章按 verdict 判
    id: 'task-20261114-0002',
    type: 'verify',
    target: 'verifier 验证审计官',
    priority: 5,
    score: 0.62,
    status: 'failed',
    retry_count: 0,
    elapsed: '6 秒',
    created: at('19:16:40'),
    assigned_agent: 'verifier',
    result: { verdict: 'needs_human' },
    trace: [
      step(null, 'pending', '19:16:40'),
      step('pending', 'dispatched', '19:16:41', { reason: 'dispatch' }),
      step('dispatched', 'running', '19:16:42'),
      step('running', 'failed', '19:16:46', { note: '置信度低于 60%，转人工' }),
    ],
  },
  {
    id: 'task-20261113-0180',
    type: 'device_cmd',
    target: 'k10-act-03 浇水 20 秒',
    priority: 3,
    score: 0.42,
    status: 'canceled',
    retry_count: 0,
    elapsed: '—',
    created: '2026-11-13T08:12:00+08:00',
    trace: [
      step(null, 'pending', '2026-11-13T08:12:00+08:00'),
      step('pending', 'canceled', '2026-11-13T08:14:22+08:00'),
    ],
  },
]

/** 后端 tasks.type 只有这 5 个（PRD 6.6） */
export const taskTypes = [
  { id: 'all', label: '全部类型' },
  { id: 'agent_call', label: '智能体调用' },
  { id: 'device_cmd', label: '设备指令' },
  { id: 'verify', label: '验证' },
  { id: 'report', label: '报告' },
] as const

export const reasonLabel: Record<string, string> = {
  dispatch: '派发',
  retry_armed: '安排重试',
  retry_due: '重试到点',
  retry_hold_offline: '设备离线，挂着等',
  retries_exhausted: '重试耗尽',
  breaker_open: '熔断打开',
  rejected_breaker_open: '被熔断拒绝',
}

export function reasonText(reason?: string): string {
  if (!reason) return ''
  if (reason.startsWith('timeout_')) return `超时 ${reason.slice(8)}`
  return reasonLabel[reason] ?? reason
}

/**
 * 统一走 lib/parseTs：后端给的是 `2026-11-14 09:30:00`（空格分隔），
 * 原生 new Date() 在 Safari / iPad 上直接 Invalid Date。
 */
export { formatClock, formatTime, parseTs, tsMillis } from '../lib/parseTs'
