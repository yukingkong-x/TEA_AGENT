import { useEffect, useRef, useState } from 'react'
import { endpoints } from '../api/endpoints'
import type { Device } from '../data/snapshot'
import { DeviceChart } from './DeviceChart'
import { Icon } from './Icon'

const statusLabel = {
  online: '在线',
  suspect: '疑似离线',
  offline: '离线',
  alarm: '报警',
}

type Point = { ts: string; value: number }

export function DeviceDrawer({ device, onClose }: { device: Device | null; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null)
  const [points, setPoints] = useState<Point[]>([])
  const [state, setState] = useState<'idle' | 'loading' | 'ok' | 'fail'>('idle')

  useEffect(() => {
    if (!device) return
    const previous = document.activeElement as HTMLElement | null
    closeRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      previous?.focus()
    }
  }, [device, onClose])

  // 曲线走后端：GET /api/sensor/history（后端已改成「先倒序取 limit 条再反转」，
  // 所以拿到的是窗口内**最新**的 N 个点，不是最老的 N 个）
  useEffect(() => {
    if (!device?.metric) {
      setState('idle')
      setPoints([])
      return
    }
    let alive = true
    setState('loading')
    setPoints([])
    endpoints
      .sensorHistory(device.id, device.metric, 24, 240)
      .then((data) => {
        if (!alive) return
        setPoints(data.points ?? [])
        setState('ok')
      })
      .catch(() => {
        if (!alive) return
        setState('fail')
      })
    return () => {
      alive = false
    }
  }, [device?.id, device?.metric])

  if (!device) return null

  const values = points.length ? points.map((item) => item.value) : device.series
  const latest = points.length ? points[points.length - 1] : null
  const first = points.length ? points[0] : null
  const delta =
    latest && first && first.value !== 0 ? ((latest.value - first.value) / Math.abs(first.value)) * 100 : null

  return (
    <div className="fixed inset-0 z-30 flex justify-end">
      <button type="button" className="absolute inset-0 bg-ink/60" aria-label="关闭设备详情" onClick={onClose} />
      <aside
        className="relative flex h-full w-full max-w-[420px] flex-col border-l border-line bg-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="device-title"
      >
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-5">
          <div>
            <p className="text-xs leading-none text-mute">
              {device.role}
              {device.isMock ? ' · Mock' : ''}
            </p>
            <h2 id="device-title" className="mt-1 text-paper">
              {device.name}
            </h2>
            <p className="mt-1 text-sm leading-normal text-mute">
              {device.id} · {device.place} · {statusLabel[device.status]}
            </p>
          </div>
          <button ref={closeRef} type="button" className="btn btn-ghost h-11 w-11 px-0" aria-label="关闭" onClick={onClose}>
            <Icon name="close" />
          </button>
        </div>
        <div className="flex-1 overflow-auto px-6 py-5">
          <dl className="grid grid-cols-3 gap-3">
            {device.detail.map((item) => (
              <div key={item.label} className="rounded-btn bg-ink px-3 py-3">
                <dt className="text-xs leading-none text-mute">{item.label}</dt>
                <dd className="num mt-2 text-base leading-none text-paper">{item.value}</dd>
              </div>
            ))}
          </dl>
          <h3 className="mt-6 text-paper">近 24 小时</h3>
          <p className="mt-1 text-sm text-mute">
            {device.seriesName}，单位 {device.unit}
            {state === 'loading' ? ' · 正在拉历史…' : ''}
            {state === 'fail' ? ' · 历史接口没通，下面只有本次会话攒到的点' : ''}
            {state === 'ok' && points.length === 0 ? ' · 这个设备还没有入库读数' : ''}
          </p>
          {delta !== null ? (
            <p className="num mt-1 text-sm leading-normal text-dim">
              窗口内 {points.length} 个点，首 {first?.value.toFixed(1)} → 末 {latest?.value.toFixed(1)}，
              {delta >= 0 ? ' 升 ' : ' 降 '}
              {Math.abs(delta).toFixed(2)}%
            </p>
          ) : null}
          <div className="mt-3 rounded-card bg-ink p-3">
            <DeviceChart device={device} values={values} stamps={points.map((item) => item.ts)} />
          </div>
        </div>
      </aside>
    </div>
  )
}
