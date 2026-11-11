import { useMemo, useState } from 'react'
import { formatClock, tasks, taskStatusMeta, taskTypes, type TaskRow, type TaskStatus } from '../data/tasks'

const statusOrder = Object.keys(taskStatusMeta) as TaskStatus[]

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
  const [range, setRange] = useState<'today' | 'day' | 'all'>('all')
  const [open, setOpen] = useState<TaskRow | null>(null)

  const rows = useMemo(
    () =>
      tasks.filter((task) => {
        if (picked.length > 0 && !picked.includes(task.status)) return false
        if (type !== 'all' && task.type !== type) return false
        return inRange(task.created, range)
      }),
    [picked, type, range],
  )

  const toggle = (status: TaskStatus) => {
    setPicked((current) => (current.includes(status) ? current.filter((item) => item !== status) : current.concat(status)))
  }

  return (
    <div className="page-enter -mt-3 mx-auto flex min-h-0 w-full max-w-[1360px] flex-1 flex-col gap-4">
      <header className="shrink-0">
        <h1 className="text-2xl font-medium leading-none">任务</h1>
        <p className="mt-2 flex items-center gap-2 text-sm text-dim">
          <span className="h-1.5 w-1.5 rounded-full bg-[#E4B423]" aria-hidden="true" />
          调度队列。点一行看状态是怎么走过来的。
        </p>
      </header>
      <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-card border border-line bg-panel">
        <div className="shrink-0 border-b border-line px-4 py-4">
        <div className="flex flex-wrap gap-2" role="group" aria-label="按状态筛选">
          {statusOrder.map((status) => {
            const meta = taskStatusMeta[status]
            const on = picked.includes(status)
            return (
              <button
                key={status}
                type="button"
                aria-pressed={on}
                onClick={() => toggle(status)}
                className={`inline-flex h-11 items-center rounded-btn border px-3 text-sm ${
                  on ? 'border-tea text-paper' : 'border-line text-dim'
                }`}
              >
                {meta.label}
              </button>
            )
          })}
        </div>
        <div className="mt-3 flex flex-wrap gap-3">
          <label className="grid gap-1 text-sm text-dim">
            类型
            <select
              className="h-11 rounded-btn border border-line bg-panel px-3 text-paper"
              value={type}
              onChange={(event) => setType(event.target.value as (typeof taskTypes)[number]['id'])}
            >
              {taskTypes.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-sm text-dim">
            时间
            <select
              className="h-11 rounded-btn border border-line bg-panel px-3 text-paper"
              value={range}
              onChange={(event) => setRange(event.target.value as 'today' | 'day' | 'all')}
            >
              <option value="all">全部时间</option>
              <option value="today">今天</option>
              <option value="day">近 24 小时</option>
            </select>
          </label>
        </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <table className="w-full min-w-[980px] border-collapse text-left text-sm">
            <thead className="sticky top-0 z-10 bg-panel text-dim">
              <tr>
                {['任务号', '类型', '目标', '优先级', '分数', '状态', '重试', '耗时', '创建时间'].map((column) => (
                  <th key={column} className="border-b border-line px-4 py-3 font-medium">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-4 py-16 text-center text-base text-dim">
                  这个筛选下面没有任务。
                </td>
              </tr>
            ) : (
              rows.map((task) => (
                <tr
                  key={task.id}
                  className="cursor-pointer border-b border-line last:border-b-0 hover:bg-ink"
                  onClick={() => setOpen(task)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      setOpen(task)
                    }
                  }}
                  tabIndex={0}
                >
                  <td className="px-4 py-3 font-medium">{task.id}</td>
                  <td className="px-4 py-3">{taskTypes.find((item) => item.id === task.type)?.label}</td>
                  <td className="px-4 py-3">{task.target}</td>
                  <td className="num px-4 py-3">{task.priority}</td>
                  <td className="num px-4 py-3">{task.score.toFixed(2)}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={task.status} />
                  </td>
                  <td className="num px-4 py-3">{task.retries}</td>
                  <td className="px-4 py-3">{task.elapsed}</td>
                  <td className="num px-4 py-3">{formatClock(task.created)}</td>
                </tr>
              ))
            )}
            </tbody>
          </table>
        </div>
      </section>
      {open ? <TraceDrawer task={open} onClose={() => setOpen(null)} /> : null}
    </div>
  )
}

function StatusBadge({ status }: { status: TaskStatus }) {
  const meta = taskStatusMeta[status]
  return <span className={`inline-flex h-7 items-center rounded-btn px-2 text-[13px] ${meta.className}`}>{meta.label}</span>
}

function TraceDrawer({ task, onClose }: { task: TaskRow; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button type="button" className="absolute inset-0 bg-[#1A1A1A]/30" aria-label="关闭轨迹" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-md flex-col border-l border-line bg-panel">
        <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <h2 className="text-xl font-medium">{task.id}</h2>
            <p className="mt-1 text-sm text-dim">{task.target}</p>
          </div>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            关闭
          </button>
        </header>
        <div className="flex-1 overflow-auto px-5 py-4">
          <p className="text-sm text-dim">状态轨迹</p>
          <ol className="mt-4 grid gap-0">
            {task.trace.map((step, index) => (
              <li key={`${step.status}-${step.at}`} className="grid grid-cols-[16px_minmax(0,1fr)] gap-3">
                <span className="flex flex-col items-center">
                  <span className="mt-1 h-2.5 w-2.5 rounded-full bg-tea" />
                  {index < task.trace.length - 1 ? <span className="w-px flex-1 bg-line" /> : null}
                </span>
                <span className="pb-4">
                  <StatusBadge status={step.status} />
                  <time className="num mt-2 block text-[13px] text-dim">{formatClock(step.at)}</time>
                </span>
              </li>
            ))}
          </ol>
        </div>
      </aside>
    </div>
  )
}
