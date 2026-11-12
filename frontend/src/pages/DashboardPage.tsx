import { useState } from 'react'
import { PageFrame } from '../components/PageFrame'
import { AlertBar } from '../components/AlertBar'
import { DeviceDrawer } from '../components/DeviceDrawer'
import { GardenMap } from '../components/GardenMap'
import { MetricTile } from '../components/MetricTile'
import { SoilChart } from '../components/SoilChart'
import { devices, metrics, type Device } from '../data/snapshot'

export function DashboardPage() {
  const [device, setDevice] = useState<Device | null>(null)

  return (
    <PageFrame title="总控">
    <div className="flex flex-col gap-4 p-5">
      <header>
        <h2 className="text-paper">A区茶垄</h2>
        <p className="mt-2 inline-flex h-8 items-center gap-2 rounded-btn bg-[#FFF4CC] px-3 text-xs leading-none text-[#6E5314]">
          <span className="h-1.5 w-1.5 rounded-full bg-[#E4B423]" aria-hidden="true" />
          土壤湿度 38.5%，低于缺水线 40%。
        </p>
      </header>
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
              tone={item.id === 'online' ? 'green' : 'plain'}
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
            <p className="mt-1 text-sm text-mute">近 24 小时，当前 38.5%。</p>
          </div>
          <div className="min-h-0 flex-1 px-2 pb-3">
            <SoilChart />
          </div>
        </section>
      </div>
      <AlertBar />
      <DeviceDrawer device={device} onClose={() => setDevice(null)} />
    </div>
    </PageFrame>
  )
}
