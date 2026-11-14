import { useState } from 'react'
import { PageFrame } from '../components/PageFrame'
import { AlertBar } from '../components/AlertBar'
import { DeviceDrawer } from '../components/DeviceDrawer'
import { GardenMap } from '../components/GardenMap'
import { MetricTile } from '../components/MetricTile'
import { SoilChart } from '../components/SoilChart'
import type { Device } from '../data/snapshot'
import { useAlerts } from '../hooks/useAlerts'
import { useDashboard } from '../hooks/useDashboard'
import { useShell } from '../shell/ShellContext'

const DRY_LINE = 40

export function DashboardPage() {
  const [device, setDevice] = useState<Device | null>(null)
  const { devices, metrics, soilSeries, soilCurrent, source, loading, error, refresh } = useDashboard()
  const { pending, ack } = useAlerts()
  const { live } = useShell()

  const soil = soilCurrent ?? 38.5
  const dry = soil < DRY_LINE

  return (
    <PageFrame title="总控">
        <div className="flex flex-col gap-4 p-5">
          <header className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-paper">A区茶垄</h2>
              <p
                className={`mt-2 inline-flex h-8 items-center gap-2 rounded-btn px-3 text-xs leading-none ${
                  dry ? 'bg-[#FFF4CC] text-[#6E5314]' : 'bg-[#E8F5EC] text-[#1F7A45]'
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${dry ? 'bg-[#E4B423]' : 'bg-[#1F7A45]'}`}
                  aria-hidden="true"
                />
                {dry
                  ? `土壤湿度 ${soil.toFixed(1)}%，低于缺水线 ${DRY_LINE}%。`
                  : `土壤湿度 ${soil.toFixed(1)}%，高于缺水线 ${DRY_LINE}%。`}
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs text-mute">
              <span
                className={`inline-flex h-6 items-center gap-1.5 rounded-btn px-2 ${
                  live ? 'bg-[#E8F5EC] text-[#1F7A45]' : 'bg-[#F2F3F5] text-[#86909C]'
                }`}
                title={live ? 'WebSocket 已连接，读数实时刷新' : 'WebSocket 未连接，数据为一次性拉取'}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${live ? 'bg-[#1F7A45]' : 'bg-[#C9CDD4]'}`} />
                {live ? '实时' : '离线'}
              </span>
              <span className="inline-flex h-6 items-center rounded-btn bg-[#F2F3F5] px-2">
                {source === 'live' ? '后端数据' : '本地样例'}
              </span>
              {loading ? <span>加载中…</span> : null}
              {error ? (
                <button type="button" className="text-[#C0392B] underline" onClick={refresh}>
                  刷新失败，重试
                </button>
              ) : null}
            </div>
          </header>
          <AlertBar alerts={pending} onAck={(id) => void ack(id)} />
          <section className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_220px]">
            <div className="relative h-[280px] overflow-hidden rounded-card border border-line sm:h-[360px] lg:h-full lg:min-h-[420px]">
              <img src="/garden/tea-rows.jpg" alt="层层茶垄延伸到远山" className="absolute inset-0 h-full w-full object-cover" />
            </div>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-1" aria-label="今日数字">
              {metrics.map((item) => (
                <MetricTile
                  key={item.id}
                  label={item.label}
                  value={item.value}
                  suffix={item.suffix}
                  hint={item.hint}
                  tone={item.id === 'loop' || item.id === 'rate' ? (item.value >= 100 ? 'green' : 'yellow') : 'plain'}
                  to={item.id === 'tasks' ? '/tasks' : undefined}
                />
              ))}
            </div>
          </section>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
            <section className="overflow-hidden rounded-2xl bg-[#F7F8FA] xl:col-span-3">
              <div className="flex items-center justify-between px-5 py-4">
                <h2 className="text-paper">地块</h2>
                <p className="text-sm text-mute">点设备看读数</p>
              </div>
              <GardenMap devices={devices} onSelect={setDevice} />
            </section>
            <section className="flex min-h-[360px] flex-col rounded-2xl bg-[#F7F8FA] xl:col-span-2">
              <div className="px-5 py-4">
                <h2 className="text-paper">土壤湿度</h2>
                <p className="mt-1 text-sm text-mute">
                  近 24 小时，当前 {soil.toFixed(1)}%。
                </p>
              </div>
              <div className="min-h-0 flex-1 px-2 pb-3">
                <SoilChart values={soilSeries} />
              </div>
            </section>
          </div>
          <DeviceDrawer device={device} onClose={() => setDevice(null)} />
        </div>
    </PageFrame>
  )
}
