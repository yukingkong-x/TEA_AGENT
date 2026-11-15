import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from 'react'
import { PageFrame } from '../components/PageFrame'
import { ApiError } from '../api/client'
import { endpoints } from '../api/endpoints'
import { dashboardSocket } from '../api/socket'
import type { DashMessage, TaskDto, TaskEventDto, TaskStatusEventDto } from '../api/types'
import {
  badgeFor,
  formatClock,
  isHoldOffline,
  parseTs,
  reasonText,
  tasks,
  taskStatusMeta,
  taskTypes,
  type TaskRow,
  type TaskStatus,
  type TaskTrace,
} from '../data/tasks'

const statusOrder = Object.keys(taskStatusMeta) as TaskStatus[]
const typeTabs = taskTypes.filter((item) => item.id !== 'all')
const timeOptions = [
  { id: 'all', label: '全部时间' },
  { id: 'today', label: '今天' },
  { id: 'day', label: '近 24 小时' },
] as const
const pageSizes = [10, 20, 50]

function inRange(iso: string, range: 'today' | 'day' | 'all') {
  const time = parseTs(iso)?.getTime()
  if (time === undefined) return true
  if (range === 'all') return true
  const now = Date.now()
  if (range === 'day') return now - time <= 24 * 60 * 60 * 1000
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  return time >= start.getTime()
}

/** 事件时间：信封给的是秒级字符串（或 epoch ms），统一成 ISO，交给 parseTs 兜底 */
function eventTime(data: { ts?: string | number }, message: DashMessage): string {
  if (typeof data.ts === 'string') return data.ts
  if (typeof data.ts === 'number') return new Date(data.ts).toISOString()
  if (typeof message.ts === 'number' && message.ts > 0) return new Date(message.ts).toISOString()
  if (typeof message.ts === 'string' && message.ts) return message.ts
  return new Date().toISOString()
}

/**
 * 把一条 task_status 事件并进列表。
 * 轨迹直接取事件里的 `from → to`，不自己推状态机。
 */
function applyEvent(rows: TaskRow[], data: TaskStatusEventDto, at: string): TaskRow[] {
  const index = rows.findIndex((row) => row.id === data.task_no)
  const step: TaskTrace = {
    from: (data.from ?? null) as TaskTrace['from'],
    to: data.to as TaskStatus,
    at,
    reason: data.reason,
    note: data.reason === 'retry_hold_offline' ? '设备离线，挂着等重试' : undefined,
  }

  if (index === -1) {
    const fresh: TaskRow = {
      id: data.task_no,
      type: data.assigned_agent && !data.assigned_device ? 'agent_call' : 'device_cmd',
      target: data.assigned_device ?? data.assigned_agent ?? '—',
      priority: 5,
      score: data.score ?? null,
      status: data.to as TaskStatus,
      retry_count: data.retry_count ?? 0,
      elapsed: '—',
      created: at,
      run_id: data.run_id ?? null,
      assigned_agent: data.assigned_agent ?? null,
      assigned_device: data.assigned_device ?? null,
      result: (data.result as TaskRow['result']) ?? null,
      trace: [step],
    }
    return [fresh, ...rows]
  }

  const current = rows[index]
  const last = current.trace[current.trace.length - 1]
  // retry_hold_offline 会反复发 from == to == retrying，合并成一步，别刷屏也别重播动画
  const trace =
    last && isHoldOffline(step) && isHoldOffline(last)
      ? current.trace.map((item, i) => (i === current.trace.length - 1 ? { ...item, at } : item))
      : current.trace.concat(step)

  const next: TaskRow = {
    ...current,
    status: data.to as TaskStatus,
    trace,
    score: data.score ?? current.score,
    retry_count: data.retry_count ?? current.retry_count,
    run_id: data.run_id ?? current.run_id,
    assigned_agent: data.assigned_agent ?? current.assigned_agent,
    assigned_device: data.assigned_device ?? current.assigned_device,
    result: (data.result as TaskRow['result']) ?? current.result,
  }
  return rows.map((row, i) => (i === index ? next : row))
}

/** 后端 TaskDto → 表格行。target/elapsed 后端没有，前端拼算。 */
function fromDto(dto: TaskDto): TaskRow {
  const payload = (dto.payload ?? {}) as { device_id?: string }
  const target = dto.assigned_device ?? dto.assigned_agent ?? payload.device_id ?? '—'
  const start = parseTs(dto.created_at ?? undefined)?.getTime()
  const end = parseTs(dto.updated_at ?? undefined)?.getTime()
  const elapsed = start && end ? `${Math.max(0, Math.round((end - start) / 1000))}s` : '—'
  return {
    id: dto.task_no,
    type: dto.type as TaskRow['type'],
    target,
    priority: dto.priority,
    score: dto.score,
    status: dto.status as TaskStatus,
    retry_count: dto.retry_count,
    elapsed,
    created: dto.created_at ?? '',
    run_id: dto.run_id,
    assigned_agent: dto.assigned_agent,
    assigned_device: dto.assigned_device,
    result: (dto.result as TaskRow['result']) ?? null,
    trace: [],
  }
}

/** GET /api/tasks/{no}/events 的一条事件 → 轨迹步（队长 11.14 上线） */
function toTraceStep(event: TaskEventDto): TaskTrace {
  const payload = (event.payload ?? {}) as {
    confidence?: number
    achievement?: number
    note?: string
    baseline_missing?: boolean
    verification_id?: number
  }
  const verify = event.event === 'verify'
  const bits: string[] = []
  if (verify) {
    if (payload.baseline_missing) bits.push('基线缺失，达成率算不出')
    else if (typeof payload.achievement === 'number') bits.push(`达成率 ${payload.achievement.toFixed(2)}%`)
    if (typeof payload.confidence === 'number') bits.push(`置信度 ${payload.confidence.toFixed(1)}%`)
    if (payload.note) bits.push(payload.note)
  }
  return {
    from: (event.from ?? null) as TaskTrace['from'],
    to: event.to as TaskStatus,
    at: event.at,
    reason: (event.reason ?? undefined) as TaskTrace['reason'],
    note: bits.length ? bits.join(' · ') : undefined,
    kind: verify ? 'verify' : 'status',
    actor: event.actor ?? undefined,
  }
}

export function TasksPage() {
  const [rows, setRows] = useState<TaskRow[]>([])
  const [source, setSource] = useState<'backend' | 'sample' | 'loading'>('loading')
  const [picked, setPicked] = useState<TaskStatus[]>([])
  const [type, setType] = useState<(typeof taskTypes)[number]['id']>('all')
  const [range, setRange] = useState<(typeof timeOptions)[number]['id']>('all')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [jump, setJump] = useState('')
  const [menu, setMenu] = useState<{ kind: 'status' | 'time'; top: number; left: number } | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)

  // 表格数据源：GET /api/tasks（最近 200 条），轨迹是抽屉里再按任务拉 events
  useEffect(() => {
    let alive = true
    endpoints
      .tasks({ page: 1, page_size: 200 })
      .then((page) => {
        if (!alive) return
        setRows((current) => {
          // 保留 WS 先到的新任务，避免请求返回时把它们覆盖掉
          const fetched = page.items.map(fromDto)
          const known = new Set(fetched.map((row) => row.id))
          return fetched.concat(current.filter((row) => !known.has(row.id)))
        })
        setSource('backend')
      })
      .catch(() => {
        if (!alive) return
        setRows((current) => (current.length ? current : tasks))
        setSource('sample')
      })
    return () => {
      alive = false
    }
  }, [])

  // 调度器的 task_status 增量续播
  useEffect(() => {
    const off = dashboardSocket.on<TaskStatusEventDto>('task_status', (data, message) => {
      if (!data?.task_no) return
      setRows((current) => applyEvent(current, data, eventTime(data, message)))
    })
    return off
  }, [])

  const view = useMemo(() => {
    const text = query.trim().toLowerCase()
    return rows.filter((task) => {
      if (picked.length > 0 && !picked.includes(task.status)) return false
      if (type !== 'all' && task.type !== type) return false
      if (!inRange(task.created, range)) return false
      if (!text) return true
      return task.id.toLowerCase().includes(text) || task.target.toLowerCase().includes(text)
    })
  }, [rows, picked, type, range, query])

  const pageCount = Math.max(1, Math.ceil(view.length / pageSize))
  const current = Math.min(page, pageCount)
  const paged = view.slice((current - 1) * pageSize, current * pageSize)
  const open = openId ? (rows.find((row) => row.id === openId) ?? null) : null

  useEffect(() => {
    setPage(1)
  }, [picked, type, range, query, pageSize])

  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [menu])

  const toggle = (status: TaskStatus) => {
    setPicked((currentStatuses) =>
      currentStatuses.includes(status) ? currentStatuses.filter((item) => item !== status) : currentStatuses.concat(status),
    )
  }

  const openMenu = (kind: 'status' | 'time', event: MouseEvent<HTMLButtonElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    setMenu((currentMenu) => (currentMenu?.kind === kind ? null : { kind, top: rect.bottom + 6, left: rect.left }))
  }

  const go = (next: number) => {
    setPage(Math.min(pageCount, Math.max(1, next)))
  }

  return (
    <PageFrame title="任务" fill>
      <section className="flex h-full min-h-0 flex-col">
        <div className="flex shrink-0 gap-6 border-b border-[#EEF0F3] px-5" role="tablist" aria-label="任务类型">
          <Tab on={type === 'all'} onClick={() => setType('all')}>
            全部
          </Tab>
          {typeTabs.map((item) => (
            <Tab key={item.id} on={type === item.id} onClick={() => setType(item.id)}>
              {item.label}
            </Tab>
          ))}
        </div>
        <div className="shrink-0 px-5 py-3">
          <label className="relative block w-[240px] max-w-full">
            <span className="sr-only">搜索任务</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索任务号或目标"
              className="h-9 w-full rounded-lg border-0 bg-[#F2F3F5] pl-9 pr-3 text-sm text-paper"
            />
            <svg viewBox="0 0 16 16" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-mute" aria-hidden="true">
              <circle cx="7" cy="7" r="4.2" fill="none" stroke="currentColor" strokeWidth="1.4" />
              <path d="M10.2 10.2 13 13" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          </label>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full min-w-[980px] border-collapse text-left text-sm leading-normal">
            <thead className="sticky top-0 z-10 bg-panel text-dim">
              <tr>
                <th className="border-b border-[#EEF0F3] px-5 py-3 font-normal">任务号</th>
                <th className="border-b border-[#EEF0F3] px-4 py-3 font-normal">类型</th>
                <th className="border-b border-[#EEF0F3] px-4 py-3 font-normal">目标</th>
                <th className="border-b border-[#EEF0F3] px-4 py-3 font-normal">优先级</th>
                <th className="border-b border-[#EEF0F3] px-4 py-3 font-normal">分数</th>
                <th className="border-b border-[#EEF0F3] px-4 py-3 font-normal">
                  <FilterButton active={picked.length > 0} open={menu?.kind === 'status'} onClick={(event) => openMenu('status', event)}>
                    状态
                  </FilterButton>
                </th>
                <th className="border-b border-[#EEF0F3] px-4 py-3 font-normal">重试</th>
                <th className="border-b border-[#EEF0F3] px-4 py-3 font-normal">耗时</th>
                <th className="border-b border-[#EEF0F3] px-4 py-3 font-normal">
                  <FilterButton active={range !== 'all'} open={menu?.kind === 'time'} onClick={(event) => openMenu('time', event)}>
                    创建时间
                  </FilterButton>
                </th>
              </tr>
            </thead>
            <tbody>
              {paged.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-5 py-16 text-center text-xs leading-normal text-mute">
                    这个筛选下面没有任务。
                  </td>
                </tr>
              ) : (
                paged.map((task) => (
                  <tr
                    key={task.id}
                    className={`cursor-pointer border-b border-[#F2F3F5] last:border-b-0 hover:bg-[#F7F8FA] ${openId === task.id ? 'bg-panel2' : ''}`}
                    onClick={() => setOpenId(task.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        setOpenId(task.id)
                      }
                    }}
                    tabIndex={0}
                  >
                    <td className="num px-5 py-3.5 text-tea">{task.id}</td>
                    <td className="px-4 py-3.5">{taskTypes.find((item) => item.id === task.type)?.label ?? task.type}</td>
                    <td className="px-4 py-3.5 text-dim">{task.target}</td>
                    <td className="num px-4 py-3.5">{task.priority}</td>
                    <td className="num px-4 py-3.5">{task.score === null ? '—' : task.score.toFixed(2)}</td>
                    <td className="px-4 py-3.5">
                      <StatusBadge task={task} />
                    </td>
                    <td className="num px-4 py-3.5">{task.retry_count}</td>
                    <td className="px-4 py-3.5">{task.elapsed}</td>
                    <td className="num px-4 py-3.5 text-dim">{formatClock(task.created)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <footer className="flex h-14 shrink-0 items-center justify-between gap-3 border-t border-[#EEF0F3] px-5 text-sm text-dim">
          <span className="flex items-center gap-2">
            共 {view.length} 条
            <span
              className={`inline-flex h-6 items-center rounded-btn px-2 text-xs leading-none ${
                source === 'backend'
                  ? 'bg-[#E5F6EA] text-[#1F7A3A]'
                  : source === 'sample'
                    ? 'bg-[#FBF3E6] text-[#9A5B12]'
                    : 'bg-[#EEF1EF] text-[#5C675F]'
              }`}
              title="表格数据来自 GET /api/tasks（最近 200 条），状态多选/时间/关键词在前端过滤"
            >
              {source === 'backend' ? '后端数据' : source === 'sample' ? '本地样例' : '载入中'}
            </span>
          </span>
          <div className="flex items-center gap-2">
            <select
              aria-label="每页条数"
              className="h-8 rounded-lg border border-[#E5E6EB] bg-panel px-2 text-sm"
              value={pageSize}
              onChange={(event) => setPageSize(Number(event.target.value))}
            >
              {pageSizes.map((size) => (
                <option key={size} value={size}>
                  {size}条/页
                </option>
              ))}
            </select>
            <PagerButton label="上一页" disabled={current <= 1} onClick={() => go(current - 1)}>
              ‹
            </PagerButton>
            <span className="grid h-8 min-w-8 place-items-center rounded-lg bg-tea px-2 text-white">{current}</span>
            <PagerButton label="下一页" disabled={current >= pageCount} onClick={() => go(current + 1)}>
              ›
            </PagerButton>
            <span className="ml-1">跳转</span>
            <input
              aria-label="跳转到页"
              inputMode="numeric"
              value={jump}
              onChange={(event) => setJump(event.target.value.replace(/\D/g, ''))}
              onKeyDown={(event) => {
                if (event.key !== 'Enter') return
                const next = Number(jump)
                if (next > 0) go(next)
                setJump('')
              }}
              className="h-8 w-12 rounded-lg border border-[#E5E6EB] bg-panel px-2 text-center text-sm text-paper"
            />
          </div>
        </footer>
      </section>
      {menu ? (
        <FilterMenu top={menu.top} left={menu.left} onClose={() => setMenu(null)}>
          {menu.kind === 'status'
            ? statusOrder.map((status) => (
                <label key={status} className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm text-paper hover:bg-[#F7F8FA]">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-tea"
                    checked={picked.includes(status)}
                    onChange={() => toggle(status)}
                  />
                  {taskStatusMeta[status].label}
                </label>
              ))
            : timeOptions.map((item) => (
                <label key={item.id} className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm text-paper hover:bg-[#F7F8FA]">
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-tea"
                    checked={range === item.id}
                    onChange={() => setRange(range === item.id ? 'all' : item.id)}
                  />
                  {item.label}
                </label>
              ))}
        </FilterMenu>
      ) : null}
      {open ? <TraceDrawer task={open} onClose={() => setOpenId(null)} /> : null}
    </PageFrame>
  )
}

function Tab({ on, onClick, children }: { on: boolean; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={on}
      onClick={onClick}
      className={`h-12 border-b-2 text-base ${on ? 'border-tea text-paper' : 'border-transparent text-dim hover:text-paper'}`}
    >
      {children}
    </button>
  )
}

function FilterButton({
  active,
  open,
  onClick,
  children,
}: {
  active: boolean
  open: boolean
  onClick: (event: MouseEvent<HTMLButtonElement>) => void
  children: string
}) {
  return (
    <button type="button" className={`inline-flex items-center gap-1 ${active || open ? 'text-tea' : ''}`} aria-expanded={open} onClick={onClick}>
      {children}
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden="true">
        <path d="M2.5 3.5h11l-4 5v3.2l-3 1.4V8.5l-4-5Z" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      </svg>
    </button>
  )
}

function FilterMenu({
  top,
  left,
  onClose,
  children,
}: {
  top: number
  left: number
  onClose: () => void
  children: ReactNode
}) {
  return (
    <>
      <button type="button" className="fixed inset-0 z-40 cursor-default" aria-label="关闭筛选" onClick={onClose} />
      <div
        className="fixed z-50 max-h-72 w-44 overflow-auto rounded-lg border border-[#EEF0F3] bg-panel py-1.5 shadow-[0_8px_24px_rgba(29,33,41,0.12)]"
        style={{ top, left }}
      >
        {children}
      </div>
    </>
  )
}

function PagerButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string
  disabled: boolean
  onClick: () => void
  children: string
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="grid h-8 w-8 place-items-center rounded-lg text-base text-dim enabled:hover:bg-[#F2F3F5] disabled:text-hold"
    >
      {children}
    </button>
  )
}

function StatusBadge({ task }: { task: Pick<TaskRow, 'status' | 'result'> }) {
  const meta = badgeFor(task)
  return <span className={`inline-flex h-6 items-center rounded-btn px-2 text-xs leading-none ${meta.className}`}>{meta.label}</span>
}

/** 一步 = 一条状态边：绘制 `from → to`，reason 只做小字说明 */
function TraceStep({ step }: { step: TaskTrace }) {
  const hold = isHoldOffline(step)
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {step.from ? (
        <>
          <StatusBadge task={{ status: step.from, result: null }} />
          <span className="text-xs text-mute" aria-hidden="true">
            →
          </span>
        </>
      ) : null}
      <StatusBadge task={{ status: step.to, result: null }} />
      {hold ? (
        <span className="inline-flex h-6 items-center rounded-btn bg-[#F7F8FA] px-2 text-xs leading-none text-mute">
          设备离线，挂着等
        </span>
      ) : null}
      {step.reason ? <span className="text-xs leading-none text-mute">{reasonText(step.reason)}</span> : null}
      {step.note ? <span className="text-xs leading-none text-mute">{step.note}</span> : null}
    </span>
  )
}

/** 浇水后要等渗透才复测：前后端都认 90s（PRD 11.2 / 队长的验证引擎） */
const PENETRATION_S = 90

/** 渗透期倒计时：返回还剩多少秒（0 = 可以复测） */
function usePenetration(startAt: string | undefined) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])
  const start = parseTs(startAt ?? undefined)?.getTime()
  if (start === undefined) return 0
  const left = Math.ceil((start + PENETRATION_S * 1000 - now) / 1000)
  return left > 0 ? left : 0
}

function TraceDrawer({ task, onClose }: { task: TaskRow; onClose: () => void }) {
  const badge = badgeFor(task)
  const [trace, setTrace] = useState<TaskTrace[]>(task.trace)
  const [state, setState] = useState<'loading' | 'ok' | 'fail'>('loading')
  const [verify, setVerify] = useState<{ busy: boolean; text: string | null; ok: boolean }>({
    busy: false,
    text: null,
    ok: true,
  })

  // 队长 11.14：GET /api/tasks/{no}/events 全量回放，打开抽屉先拉一次，
  // 之后 WS task_status 的增量已经并进 task.trace，这里把两边按 at 排序合并即可。
  useEffect(() => {
    let alive = true
    setState('loading')
    endpoints
      .taskEvents(task.id)
      .then((page) => {
        if (!alive) return
        setTrace(page.items.map(toTraceStep))
        setState('ok')
      })
      .catch(() => {
        if (!alive) return
        setTrace(task.trace)
        setState('fail')
      })
    return () => {
      alive = false
    }
  }, [task.id])

  // 抽屉开着的时候 WS 还在往里写 task.trace：把事件接口没覆盖到的新step 续上，
  // 按 (from,to,at) 去重，否则同一跳会画两遍
  const merged = useMemo(() => {
    const seen = new Set(trace.map((step) => `${step.from ?? ''}>${step.to}@${step.at}`))
    const extra = task.trace.filter((step) => !seen.has(`${step.from ?? ''}>${step.to}@${step.at}`))
    return extra.length ? trace.concat(extra) : trace
  }, [trace, task.trace])

  // 只有「浇过水」的任务才需要等渗透：device_cmd 类型的最后一条状态就是浇水完成时刻
  const lastAt = merged.length ? merged[merged.length - 1].at : task.created
  const waitLeft = usePenetration(task.type === 'device_cmd' ? lastAt : undefined)
  const canVerify = task.type === 'device_cmd' && !task.result?.rejected && waitLeft === 0 && !verify.busy

  async function runVerify() {
    setVerify({ busy: true, text: null, ok: true })
    try {
      await endpoints.verifyTask(task.id)
      setVerify({ busy: false, text: '复测已下发，结果会以 verify 事件回到这条轨迹里（虚线那一跳）。', ok: true })
    } catch (err) {
      const msg = err instanceof ApiError ? (err.notReady ? '验证引擎接入中（SEAM_NOT_READY）' : err.message) : String(err)
      setVerify({ busy: false, text: `复测失败：${msg}`, ok: false })
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button type="button" className="absolute inset-0 bg-paper/30" aria-label="关闭轨迹" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-md flex-col border-l border-line bg-panel">
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <h2 className="num text-paper">{task.id}</h2>
            <p className="mt-1 text-sm leading-normal text-mute">{task.target}</p>
            <span className={`mt-2 inline-flex h-6 items-center rounded-btn px-2 text-xs leading-none ${badge.className}`}>
              {badge.label}
            </span>
          </div>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            关闭
          </button>
        </header>
        <div className="flex-1 overflow-auto px-5 py-4">
          <h3 className="text-paper">状态轨迹</h3>
          <p className="mt-1 text-xs leading-normal text-mute">
            打开时从 /api/tasks/{task.id}/events 全量回放，之后接 WS task_status 增量；按 from → to 原样画，验证那一跳是虚线。
          </p>
          {state === 'fail' ? (
            <p className="mt-2 text-xs leading-normal text-[#9A5B12]">事件接口没通，下面只显示本次会话里收到的 WS 事件。</p>
          ) : null}
          {state === 'loading' && trace.length === 0 ? (
            <p className="mt-3 text-sm leading-normal text-mute">正在拉事件…</p>
          ) : null}
          <ol className="mt-4 grid gap-0">
            {merged.map((step, index) => (
              <li key={`${step.from ?? 'new'}-${step.to}-${step.at}-${index}`} className="grid grid-cols-[16px_minmax(0,1fr)] gap-3">
                <span className="flex flex-col items-center">
                  {step.kind === 'verify' ? (
                    <span className="mt-1 h-2.5 w-2.5 rounded-full border border-dashed border-[#6D28D9] bg-panel" />
                  ) : (
                    <span className={`mt-1 h-2.5 w-2.5 rounded-full ${isHoldOffline(step) ? 'bg-[#C9CDD4]' : 'bg-tea'}`} />
                  )}
                  {index < merged.length - 1 ? (
                    <span className={`w-px flex-1 ${step.kind === 'verify' ? 'bg-[repeating-linear-gradient(to_bottom,#6D28D9_0_3px,transparent_3px_6px)]' : 'bg-line'}`} />
                  ) : null}
                </span>
                <span className="pb-4">
                  <TraceStep step={step} />
                  <time className="num mt-2 block text-xs leading-none text-mute">
                    {formatClock(step.at)}
                    {step.actor ? ` · ${step.actor}` : ''}
                  </time>
                </span>
              </li>
            ))}
          </ol>

          {task.type === 'device_cmd' ? (
            <div className="mt-2 rounded-btn border border-line px-3 py-3">
              <p className="text-sm leading-normal text-paper">复测</p>
              <p className="mt-1 text-xs leading-normal text-mute">
                浇完水要等渗透期 ≥{PENETRATION_S}s 才有 3 条稳定读数，早复测会拿到偏低值误判成未达标。
              </p>
              <button
                type="button"
                disabled={!canVerify}
                onClick={() => void runVerify()}
                className="mt-2 h-9 rounded-btn bg-tea px-3 text-sm text-white hover:bg-teaHover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {verify.busy ? '复测中…' : waitLeft > 0 ? `等渗透期 ${waitLeft}s` : '立即复测'}
              </button>
              {verify.text ? (
                <p className={`mt-2 text-xs leading-normal ${verify.ok ? 'text-mute' : 'text-danger'}`}>{verify.text}</p>
              ) : null}
            </div>
          ) : null}
          {task.result ? (
            <>
              <h3 className="mt-2 text-paper">结果</h3>
              {task.result.rejected === 'breaker_open' ? (
                <p className="mt-2 rounded-btn bg-[#3F1212] px-3 py-2 text-sm leading-normal text-[#F8D0D0]">
                  熔断拒绝：冷却剩余 {task.result.retry_after_s ?? '—'}s，冷却结束前不再派发。
                </p>
              ) : null}
              {task.result.verdict === 'needs_human' ? (
                <p className="mt-2 rounded-btn bg-[#F3E8FF] px-3 py-2 text-sm leading-normal text-[#6D28D9]">
                  验证结论：置信度低于 60%，已转人工判定（枚举补齐前落 failed + verdict）。
                </p>
              ) : null}
              <pre className="num mt-2 overflow-auto rounded-lg bg-[#F7F8FA] p-3 text-xs leading-normal text-dim">
                {JSON.stringify(task.result, null, 2)}
              </pre>
            </>
          ) : null}
        </div>
      </aside>
    </div>
  )
}
