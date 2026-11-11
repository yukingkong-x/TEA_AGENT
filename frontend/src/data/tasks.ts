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

export type TaskTrace = {
  status: TaskStatus
  at: string
}

export type TaskRow = {
  id: string
  type: 'device_cmd' | 'alert' | 'verify'
  target: string
  priority: number
  score: number
  status: TaskStatus
  retries: number
  elapsed: string
  created: string
  trace: TaskTrace[]
}

export const taskStatusMeta: Record<TaskStatus, { label: string; className: string }> = {
  pending: { label: '排队', className: 'bg-[#EEF1EF] text-[#5C675F]' },
  dispatched: { label: '已派发', className: 'bg-[#E7F3EA] text-[#1F5C36]' },
  running: { label: '执行中', className: 'bg-[#E7F0FA] text-[#1D4ED8] badge-flash' },
  success: { label: '成功', className: 'bg-[#E5F6EA] text-[#1F7A3A]' },
  failed: { label: '失败', className: 'bg-[#FDECEC] text-[#B42318]' },
  timeout: { label: '超时', className: 'bg-[#FDECEC] text-[#C2410C]' },
  retrying: { label: '重试', className: 'bg-[#FBF3E6] text-[#9A5B12]' },
  dead: { label: '熔断', className: 'bg-[#3F1212] text-[#F8D0D0]' },
  needs_human: { label: '转人工', className: 'bg-[#F3E8FF] text-[#6D28D9]' },
  canceled: { label: '取消', className: 'bg-[#EEF1EF] text-[#5C675F]' },
}

const day = '2026-11-11'

function at(clock: string) {
  return `${day}T${clock}+08:00`
}

export const tasks: TaskRow[] = [
  {
    id: 'task-1101',
    type: 'device_cmd',
    target: 'k10-act-03 浇水 30 秒',
    priority: 6,
    score: 0.69,
    status: 'running',
    retries: 0,
    elapsed: '进行中',
    created: at('21:06:03'),
    trace: [
      { status: 'pending', at: at('21:06:01') },
      { status: 'dispatched', at: at('21:06:02') },
      { status: 'running', at: at('21:06:03') },
    ],
  },
  {
    id: 'task-1107',
    type: 'verify',
    target: 'esp32-soil-02 复测',
    priority: 8,
    score: 0.77,
    status: 'dispatched',
    retries: 0,
    elapsed: '1 秒',
    created: at('21:07:40'),
    trace: [
      { status: 'pending', at: at('21:07:40') },
      { status: 'dispatched', at: at('21:07:41') },
    ],
  },
  {
    id: 'task-1106',
    type: 'device_cmd',
    target: 'k10-field-01 补测环境',
    priority: 4,
    score: 0.51,
    status: 'pending',
    retries: 0,
    elapsed: '—',
    created: at('21:08:12'),
    trace: [{ status: 'pending', at: at('21:08:12') }],
  },
  {
    id: 'task-1102',
    type: 'device_cmd',
    target: 'k10-act-03 浇水 30 秒',
    priority: 6,
    score: 0.59,
    status: 'retrying',
    retries: 1,
    elapsed: '8 秒',
    created: at('20:41:02'),
    trace: [
      { status: 'pending', at: at('20:41:02') },
      { status: 'dispatched', at: at('20:41:03') },
      { status: 'running', at: at('20:41:04') },
      { status: 'timeout', at: at('20:41:10') },
      { status: 'retrying', at: at('20:41:10') },
    ],
  },
  {
    id: 'task-1103',
    type: 'device_cmd',
    target: 'k10-act-03 浇水 30 秒',
    priority: 6,
    score: 0.59,
    status: 'timeout',
    retries: 2,
    elapsed: '14 秒',
    created: at('20:42:16'),
    trace: [
      { status: 'pending', at: at('20:42:16') },
      { status: 'dispatched', at: at('20:42:17') },
      { status: 'running', at: at('20:42:18') },
      { status: 'timeout', at: at('20:42:24') },
      { status: 'retrying', at: at('20:42:24') },
      { status: 'running', at: at('20:42:28') },
      { status: 'timeout', at: at('20:42:34') },
    ],
  },
  {
    id: 'task-1104',
    type: 'device_cmd',
    target: 'k10-act-03 浇水 30 秒',
    priority: 6,
    score: 0.49,
    status: 'dead',
    retries: 3,
    elapsed: '26 秒',
    created: at('20:44:01'),
    trace: [
      { status: 'pending', at: at('20:44:01') },
      { status: 'dispatched', at: at('20:44:02') },
      { status: 'running', at: at('20:44:03') },
      { status: 'timeout', at: at('20:44:09') },
      { status: 'retrying', at: at('20:44:09') },
      { status: 'timeout', at: at('20:44:15') },
      { status: 'retrying', at: at('20:44:15') },
      { status: 'timeout', at: at('20:44:23') },
      { status: 'dead', at: at('20:44:27') },
    ],
  },
  {
    id: 'task-1094',
    type: 'alert',
    target: 'scout 巡园管家',
    priority: 7,
    score: 0.73,
    status: 'success',
    retries: 0,
    elapsed: '1 秒',
    created: at('21:02:18'),
    trace: [
      { status: 'pending', at: at('21:02:18') },
      { status: 'dispatched', at: at('21:02:18') },
      { status: 'running', at: at('21:02:19') },
      { status: 'success', at: at('21:02:19') },
    ],
  },
  {
    id: 'task-1098',
    type: 'verify',
    target: 'verifier 验证审计官',
    priority: 5,
    score: 0.62,
    status: 'needs_human',
    retries: 0,
    elapsed: '6 秒',
    created: at('19:16:40'),
    trace: [
      { status: 'pending', at: at('19:16:40') },
      { status: 'running', at: at('19:16:42') },
      { status: 'needs_human', at: at('19:16:46') },
    ],
  },
  {
    id: 'task-1088',
    type: 'device_cmd',
    target: 'k10-act-03 浇水 20 秒',
    priority: 6,
    score: 0.59,
    status: 'failed',
    retries: 1,
    elapsed: '11 秒',
    created: at('18:22:05'),
    trace: [
      { status: 'pending', at: at('18:22:05') },
      { status: 'running', at: at('18:22:07') },
      { status: 'failed', at: at('18:22:16') },
    ],
  },
  {
    id: 'task-1080',
    type: 'device_cmd',
    target: 'k10-act-03 浇水 20 秒',
    priority: 3,
    score: 0.42,
    status: 'canceled',
    retries: 0,
    elapsed: '—',
    created: '2026-11-10T18:12:00+08:00',
    trace: [
      { status: 'pending', at: '2026-11-10T18:12:00+08:00' },
      { status: 'canceled', at: '2026-11-10T18:14:22+08:00' },
    ],
  },
]

export const taskTypes = [
  { id: 'all', label: '全部类型' },
  { id: 'device_cmd', label: '设备指令' },
  { id: 'alert', label: '报警' },
  { id: 'verify', label: '验证' },
] as const

export function formatClock(iso: string) {
  const date = new Date(iso)
  const month = `${date.getMonth() + 1}`.padStart(2, '0')
  const dayNum = `${date.getDate()}`.padStart(2, '0')
  const hour = `${date.getHours()}`.padStart(2, '0')
  const minute = `${date.getMinutes()}`.padStart(2, '0')
  const second = `${date.getSeconds()}`.padStart(2, '0')
  return `${month}-${dayNum} ${hour}:${minute}:${second}`
}
