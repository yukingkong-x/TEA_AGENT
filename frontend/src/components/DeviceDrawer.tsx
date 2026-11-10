import { useEffect, useRef } from 'react'
import type { Device } from '../data/snapshot'
import { DeviceChart } from './DeviceChart'
import { Icon } from './Icon'

const statusLabel = {
  online: '在线',
  suspect: '疑似离线',
  offline: '离线',
  alarm: '报警',
}

export function DeviceDrawer({ device, onClose }: { device: Device | null; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null)

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

  if (!device) return null

  return (
    <div className="fixed inset-0 z-30 flex justify-end">
      <button type="button" className="absolute inset-0 bg-ink/60" aria-label="关闭设备详情" onClick={onClose} />
      <aside className="relative flex h-full w-full max-w-[420px] flex-col border-l border-line bg-panel" role="dialog" aria-modal="true" aria-labelledby="device-title">
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-5">
          <div>
            <p className="text-[13px] text-dim">{device.role}</p>
            <h2 id="device-title" className="mt-1 text-xl font-medium">
              {device.name}
            </h2>
            <p className="mt-1 text-sm text-dim">
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
                <dt className="text-[13px] text-dim">{item.label}</dt>
                <dd className="num mt-2 text-lg text-paper">{item.value}</dd>
              </div>
            ))}
          </dl>
          <h3 className="mt-6 text-base font-medium">近 12 个读数</h3>
          <p className="mt-1 text-sm text-dim">
            {device.seriesName}，单位 {device.unit}
          </p>
          <div className="mt-3 rounded-card bg-ink p-3">
            <DeviceChart device={device} />
          </div>
        </div>
      </aside>
    </div>
  )
}
