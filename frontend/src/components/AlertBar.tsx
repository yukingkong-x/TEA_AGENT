import { useEffect, useRef, useState } from 'react'
import { formatClock } from '../lib/parseTs'
import { sourceLabel, type AlertItem } from '../hooks/useAlerts'
import { ConfirmDialog } from './ConfirmDialog'

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

/** 下拉里最多摊开几条，再多就只给计数（避免浮层长到把大屏糊住） */
const DROPDOWN_LIMIT = 10

/**
 * 大屏顶部报警条。
 *
 * 设计口径：**默认只露一条**（严重度优先、同级取最新），其余收进右侧下拉浮层。
 * 以前平铺 3 条 + 一行"还有 N 条"，一旦设备反复掉线，大屏第一屏全被警告占据，
 * 演示时观众看到的是"系统一直在报错"。单条 + 可展开既保住告警的可见性，
 * 又让总控回归"一屏一眼看完"。
 *
 * 交互：点「还有 N 条」展开 → 单条可确认；「一键清除」二次确认后全部置为已确认
 * （不删记录，任务页仍可回看）；点浮层外部 / Esc 收起；浮层 120ms 淡入。
 */
export function AlertBar({
  alerts,
  onAck,
  onAckAll,
}: {
  alerts: AlertItem[]
  onAck: (id: number) => void
  onAckAll: () => void
}) {
  const [open, setOpen] = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const rootRef = useRef<HTMLElement | null>(null)

  // 清空后把浮层收掉，否则下一条报警进来会直接弹着下拉
  useEffect(() => {
    if (alerts.length === 0) {
      setOpen(false)
      setConfirmClear(false)
    }
  }, [alerts.length])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent | TouchEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('touchstart', onPointerDown)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('touchstart', onPointerDown)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  if (alerts.length === 0) return null

  const [top, ...rest] = alerts
  const style = LEVEL_STYLE[top.level] ?? LEVEL_STYLE.info
  const shownRest = rest.slice(0, DROPDOWN_LIMIT)
  const hiddenCount = rest.length - shownRest.length

  return (
    <section ref={rootRef} aria-label="未确认报警" className="relative">
      <div
        role="alert"
        className={`flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border px-4 py-2.5 ${style.bar}`}
      >
        <span className={`inline-flex h-6 shrink-0 items-center rounded-btn px-2 text-xs leading-none ${style.chip}`}>
          {style.label}
        </span>
        <span className="min-w-0 flex-1 truncate text-sm leading-normal text-paper" title={top.message}>
          {top.message}
        </span>
        <span className="num shrink-0 text-xs leading-none text-mute">
          {sourceLabel(top.source)} · {formatClock(top.at)}
        </span>
        <button
          type="button"
          className={`h-8 shrink-0 rounded-btn bg-panel px-3 text-xs leading-none hover:underline ${style.text}`}
          onClick={() => onAck(top.id)}
        >
          确认
        </button>

        {rest.length > 0 ? (
          <button
            type="button"
            aria-expanded={open}
            aria-controls="alert-more-panel"
            className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-btn bg-panel px-3 text-xs leading-none ${style.text}`}
            onClick={() => setOpen((value) => !value)}
          >
            还有 {rest.length} 条
            <span className={`transition-transform duration-150 ${open ? 'rotate-180' : ''}`} aria-hidden="true">
              ▾
            </span>
          </button>
        ) : null}

        <button
          type="button"
          className="h-8 shrink-0 rounded-btn border border-[#E3EBE6] bg-panel px-3 text-xs leading-none text-[#4E5969] hover:border-[#C9CDD4]"
          onClick={() => setConfirmClear(true)}
        >
          一键清除
        </button>
      </div>

      {open && rest.length > 0 ? (
        <div
          id="alert-more-panel"
          className="alert-pop absolute right-0 top-full z-30 mt-2 w-full max-w-[760px] overflow-hidden rounded-card border border-line bg-panel shadow-[0_18px_40px_-16px_rgba(29,33,41,0.28)]"
        >
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <p className="text-xs leading-none text-dim">其余未确认报警 · 共 {alerts.length} 条</p>
            <button
              type="button"
              className="text-xs leading-none text-mute hover:text-paper"
              onClick={() => setOpen(false)}
            >
              收起
            </button>
          </div>
          <ul className="max-h-[300px] overflow-y-auto py-1">
            {shownRest.map((alert) => {
              const rowStyle = LEVEL_STYLE[alert.level] ?? LEVEL_STYLE.info
              return (
                <li key={alert.id} className="flex items-center gap-3 px-4 py-2 hover:bg-panel2/60">
                  <span
                    className={`inline-flex h-5 w-11 shrink-0 items-center justify-center rounded-btn text-[11px] leading-none ${rowStyle.chip}`}
                  >
                    {rowStyle.label}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-sm leading-normal text-paper" title={alert.message}>
                    {alert.message}
                  </span>
                  <span className="num shrink-0 text-[11px] leading-none text-mute">
                    {sourceLabel(alert.source)} · {formatClock(alert.at)}
                  </span>
                  <button
                    type="button"
                    className="h-7 shrink-0 rounded-btn border border-line px-2.5 text-[11px] leading-none text-dim hover:border-[#C9CDD4] hover:text-paper"
                    onClick={() => onAck(alert.id)}
                  >
                    确认
                  </button>
                </li>
              )
            })}
          </ul>
          {hiddenCount > 0 ? (
            <p className="border-t border-line px-4 py-2 text-xs leading-none text-mute">
              另有 {hiddenCount} 条较旧的报警未在此列出
            </p>
          ) : null}
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmClear}
        title="清除全部未确认报警"
        body={`当前 ${alerts.length} 条未确认报警将被标记为已确认。记录不会删除，仍可在任务页回看；若设备真的异常，下一轮巡检会重新报警。`}
        confirmLabel="全部确认"
        onClose={() => setConfirmClear(false)}
        onConfirm={() => {
          setConfirmClear(false)
          setOpen(false)
          onAckAll()
        }}
      />
    </section>
  )
}
