import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from 'react'
import { PageFrame } from '../components/PageFrame'
import { formatClock, tasks, taskStatusMeta, taskTypes, type TaskRow, type TaskStatus } from '../data/tasks'

const statusOrder = Object.keys(taskStatusMeta) as TaskStatus[]
const typeTabs = taskTypes.filter((item) => item.id !== 'all')
const timeOptions = [
  { id: 'all', label: '全部时间' },
  { id: 'today', label: '今天' },
  { id: 'day', label: '近 24 小时' },
] as const
const pageSizes = [10, 20, 50]

function inRange(iso: string, range: 'today' | 'day' | 'all') {
  const time = new Date(iso).getTime()
  if (range === 'all') return true
  const now = Date.now()
  if (range === 'day') return now - time <= 24 * 60 * 60 * 1000
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  return time >= start.getTime()
}

export function TasksPage() {
  const [picked, setPicked] = useState<TaskStatus[]>([])
  const [type, setType] = useState<(typeof taskTypes)[number]['id']>('all')
  const [range, setRange] = useState<(typeof timeOptions)[number]['id']>('all')
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [jump, setJump] = useState('')
  const [menu, setMenu] = useState<{ kind: 'status' | 'time'; top: number; left: number } | null>(null)
  const [open, setOpen] = useState<TaskRow | null>(null)

  const rows = useMemo(() => {
    const text = query.trim().toLowerCase()
    return tasks.filter((task) => {
      if (picked.length > 0 && !picked.includes(task.status)) return false
      if (type !== 'all' && task.type !== type) return false
      if (!inRange(task.created, range)) return false
      if (!text) return true
      return task.id.toLowerCase().includes(text) || task.target.toLowerCase().includes(text)
    })
  }, [picked, type, range, query])

  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize))
  const current = Math.min(page, pageCount)
  const view = rows.slice((current - 1) * pageSize, current * pageSize)

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
              {view.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-5 py-16 text-center text-xs leading-normal text-mute">
                    这个筛选下面没有任务。
                  </td>
                </tr>
              ) : (
                view.map((task) => (
                  <tr
                    key={task.id}
                    className={`cursor-pointer border-b border-[#F2F3F5] last:border-b-0 hover:bg-[#F7F8FA] ${open?.id === task.id ? 'bg-panel2' : ''}`}
                    onClick={() => setOpen(task)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        setOpen(task)
                      }
                    }}
                    tabIndex={0}
                  >
                    <td className="num px-5 py-3.5 text-tea">{task.id}</td>
                    <td className="px-4 py-3.5">{taskTypes.find((item) => item.id === task.type)?.label}</td>
                    <td className="px-4 py-3.5 text-dim">{task.target}</td>
                    <td className="num px-4 py-3.5">{task.priority}</td>
                    <td className="num px-4 py-3.5">{task.score.toFixed(2)}</td>
                    <td className="px-4 py-3.5">
                      <StatusBadge status={task.status} />
                    </td>
                    <td className="num px-4 py-3.5">{task.retries}</td>
                    <td className="px-4 py-3.5">{task.elapsed}</td>
                    <td className="num px-4 py-3.5 text-dim">{formatClock(task.created)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <footer className="flex h-14 shrink-0 items-center justify-between gap-3 border-t border-[#EEF0F3] px-5 text-sm text-dim">
          <span>共 {rows.length} 条</span>
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
      {open ? <TraceDrawer task={open} onClose={() => setOpen(null)} /> : null}
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

function StatusBadge({ status }: { status: TaskStatus }) {
  const meta = taskStatusMeta[status]
  return <span className={`inline-flex h-6 items-center rounded-btn px-2 text-xs leading-none ${meta.className}`}>{meta.label}</span>
}

function TraceDrawer({ task, onClose }: { task: TaskRow; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button type="button" className="absolute inset-0 bg-paper/30" aria-label="关闭轨迹" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-md flex-col border-l border-line bg-panel">
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <h2 className="num text-paper">{task.id}</h2>
            <p className="mt-1 text-sm leading-normal text-mute">{task.target}</p>
          </div>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            关闭
          </button>
        </header>
        <div className="flex-1 overflow-auto px-5 py-4">
          <h3 className="text-paper">状态轨迹</h3>
          <ol className="mt-4 grid gap-0">
            {task.trace.map((step, index) => (
              <li key={`${step.status}-${step.at}`} className="grid grid-cols-[16px_minmax(0,1fr)] gap-3">
                <span className="flex flex-col items-center">
                  <span className="mt-1 h-2.5 w-2.5 rounded-full bg-tea" />
                  {index < task.trace.length - 1 ? <span className="w-px flex-1 bg-line" /> : null}
                </span>
                <span className="pb-4">
                  <StatusBadge status={step.status} />
                  <time className="num mt-2 block text-xs leading-none text-mute">{formatClock(step.at)}</time>
                </span>
              </li>
            ))}
          </ol>
        </div>
      </aside>
    </div>
  )
}
