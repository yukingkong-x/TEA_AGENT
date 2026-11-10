import { useState } from 'react'
import { AlertBar } from '../components/AlertBar'
import { DeviceDrawer } from '../components/DeviceDrawer'
import { GardenMap } from '../components/GardenMap'
import { GardenPhoto } from '../components/GardenPhoto'
import { MetricTile } from '../components/MetricTile'
import { SoilChart } from '../components/SoilChart'
import { devices, metrics, type Device } from '../data/snapshot'

export function DashboardPage() {
  const [device, setDevice] = useState<Device | null>(null)

  return (
    <div className="page-enter mx-auto flex w-full max-w-[1360px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3 pt-2">
        <div>
          <p className="text-[13px] text-dim">总控</p>
          <h1 className="mt-1 text-[40px] leading-none text-paper">A区茶垄</h1>
          <p className="mt-3 max-w-[40rem] text-base text-dim">土壤湿度 38.5%，低于缺水线 40%。</p>
        </div>
      </header>
      <GardenPhoto src="/garden/rows.svg" label="一层层茶垄" />
      <section aria-label="今日数字" className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((item) => (
          <MetricTile key={item.id} label={item.label} value={item.value} suffix={item.suffix} hint={item.hint} />
        ))}
      </section>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <section className="overflow-hidden rounded-card border border-line bg-panel xl:col-span-3">
          <div className="flex items-center justify-between px-5 py-4">
            <h2 className="text-base font-medium">地块</h2>
            <p className="text-sm text-dim">点设备看读数</p>
          </div>
          <GardenMap devices={devices} onSelect={setDevice} />
        </section>
        <section className="flex min-h-[360px] flex-col rounded-card border border-line bg-panel xl:col-span-2">
          <div className="px-5 py-4">
            <h2 className="text-base font-medium">土壤湿度</h2>
            <p className="mt-1 text-sm text-dim">近 24 小时，当前 38.5%。</p>
          </div>
          <div className="min-h-0 flex-1 px-2 pb-3">
            <SoilChart />
          </div>
        </section>
      </div>
      <AlertBar />
      <DeviceDrawer device={device} onClose={() => setDevice(null)} />
    </div>
  )
}
