import { formatClock } from '../lib/parseTs'
import { sourceLabel, type AlertItem } from '../hooks/useAlerts'

const LEVEL_STYLE: Record<string, { bar: string; chip: string; text: string; label: string }> = {
  critical: {
    bar: 'bg-[#FFECE8] border-[#F5C2BB]',
    chip: 'bg-[#C0392B] text-white',
    text: 'text-[#8E2418]',
    label: '严重',
  },
  warning: {
    bar: 'bg-[#FFF4CC] border-[#EBD79A]',
    chip: 'bg-[#E4B423] text-[#3B2C05]',
    text: 'text-[#6E5314]',
    label: '警告',
  },
  info: {
    bar: 'bg-[#F2F5FF] border-[#CBD8F5]',
    chip: 'bg-[#3B6FD4] text-white',
    text: 'text-[#24417E]',
    label: '提示',
  },
}

/** 大屏顶部报警条：只显示未确认的，按严重度排序，最多 3 条 */
export function AlertBar({
  alerts,
  onAck,
}: {
  alerts: AlertItem[]
  onAck: (id: number) => void
}) {
  if (alerts.length === 0) return null
  const shown = alerts.slice(0, 3)

  return (
    <section aria-label="未确认报警" className="grid gap-2">
      {shown.map((alert) => {
        const style = LEVEL_STYLE[alert.level] ?? LEVEL_STYLE.info
        return (
          <div
            key={alert.id}
            role="alert"
            className={`flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 ${style.bar}`}
          >
            <span className={`inline-flex h-6 shrink-0 items-center rounded-btn px-2 text-xs leading-none ${style.chip}`}>
              {style.label}
            </span>
            <span className="min-w-0 flex-1 text-sm leading-normal text-paper">{alert.message}</span>
            <span className="num shrink-0 text-xs leading-none text-mute">
              {sourceLabel(alert.source)} · {formatClock(alert.at)}
            </span>
            <button
              type="button"
              className={`h-8 shrink-0 rounded-btn bg-panel px-3 text-xs leading-none hover:underline ${style.text}`}
              onClick={() => onAck(alert.id)}
            >
              确认
            </button>
          </div>
        )
      })}
      {alerts.length > shown.length ? (
        <p className="text-xs leading-none text-mute">还有 {alerts.length - shown.length} 条未确认报警，去任务页看全量。</p>
      ) : null}
    </section>
  )
}
