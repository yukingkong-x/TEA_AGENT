import { useState } from 'react'
import { PageFrame } from '../components/PageFrame'
import { AlertBar } from '../components/AlertBar'
import { DeviceDrawer } from '../components/DeviceDrawer'
import { GardenMap } from '../components/GardenMap'
import { GlassCard } from '../components/GlassCard'
import { LoopCard } from '../components/LoopCard'
import { MetricTile } from '../components/MetricTile'
import { SensorPanel } from '../components/SensorPanel'
import type { Device } from '../data/snapshot'
import { useAlerts } from '../hooks/useAlerts'
import { useDashboard } from '../hooks/useDashboard'
import { useShell } from '../shell/ShellContext'

const DRY_LINE = 40

export function DashboardPage() {
  const [device, setDevice] = useState<Device | null>(null)
  const { devices, metrics, feed, link, day, source, loading, error, refresh } = useDashboard()
  const { pending, ack, ackAll } = useAlerts()
  const { live } = useShell()

  /**
   * 顶部墒情胶囊：0 / -999 不是「极度干旱」，是**探头没插进土里**（哨兵值）。
   * 以前 `soilCurrent ?? 38.5` 会兜一个假数出来，这里一律按无效处理并如实说明。
   */
  const soilRaw = feed.soil_moisture?.value ?? null
  /** 地块只画真机：早期模拟器注册的 mock-* 设备记录还在库里，别再画出来混淆视听 */
  const realDevices = devices.filter((item) => !item.isMock)
  const soilValid = soilRaw !== null && soilRaw > 0.5 && soilRaw <= 100
  const dry = soilValid && soilRaw < DRY_LINE
  const soilTone = !soilValid ? 'idle' : dry ? 'dry' : 'ok'
  const soilText = !soilValid
    ? soilRaw === null
      ? '土壤读数等待上报'
      : `土壤探头未插入（读数 ${soilRaw.toFixed(1)}%，不作灌溉依据）`
    : dry
      ? `土壤湿度 ${soilRaw.toFixed(1)}%，低于缺水线 ${DRY_LINE}%`
      : `土壤湿度 ${soilRaw.toFixed(1)}%，高于缺水线 ${DRY_LINE}%`

  return (
    <PageFrame title="总控">
        <div className="flex flex-col gap-4 p-5">
          <header className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-paper">A区茶垄</h2>
              <p
                className={`mt-2 inline-flex h-8 items-center gap-2 rounded-btn px-3 text-xs leading-none ${
                  soilTone === 'idle'
                    ? 'bg-[#F2F3F5] text-[#86909C]'
                    : soilTone === 'dry'
                      ? 'bg-[#FFF4CC] text-[#6E5314]'
                      : 'bg-[#E8F5EC] text-[#1F7A45]'
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    soilTone === 'idle' ? 'bg-[#C9CDD4]' : soilTone === 'dry' ? 'bg-[#E4B423]' : 'bg-[#1F7A45]'
                  }`}
                  aria-hidden="true"
                />
                {soilText}
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
          <AlertBar alerts={pending} onAck={(id) => void ack(id)} onAckAll={() => void ackAll()} />
          <SensorPanel feed={feed} link={link} day={day} />
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
            <GlassCard className="overflow-hidden xl:col-span-3" tilt={false} label="地块设备分布">
              <div className="flex items-center justify-between px-5 py-4">
                <h2 className="text-paper">地块</h2>
                <p className="text-sm text-mute">点设备看读数</p>
              </div>
              <GardenMap devices={realDevices} onSelect={setDevice} />
            </GlassCard>
            <LoopCard />
          </div>
          <DeviceDrawer device={device} onClose={() => setDevice(null)} />
        </div>
    </PageFrame>
  )
}
