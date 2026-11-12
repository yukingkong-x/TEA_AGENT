import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { Device } from '../data/snapshot'

export function DeviceChart({ device }: { device: Device }) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const node = host.current
    if (!node) return
    const chart = echarts.init(node, undefined, { renderer: 'canvas' })
    const flat = device.series.every((point) => point === device.series[0])
    chart.setOption({
      backgroundColor: 'transparent',
      animationDuration: 400,
      grid: { left: 36, right: 8, top: 16, bottom: 24 },
      xAxis: {
        type: 'category',
        data: device.series.map((_, index) => `${index + 1}`),
        axisLine: { lineStyle: { color: '#E3EBE6' } },
        axisTick: { show: false },
        axisLabel: { show: false },
      },
      yAxis: {
        type: 'value',
        min: flat ? 0 : undefined,
        max: flat ? 1 : undefined,
        splitLine: { lineStyle: { color: '#EFEAE3' } },
        axisLabel: { color: '#86909C', fontSize: 12, fontFamily: 'DIN, DIN Alternate, sans-serif' },
      },
      series: [
        {
          type: 'line',
          data: device.series,
          smooth: 0.2,
          symbol: 'none',
          lineStyle: { color: '#1F7A45', width: 2 },
        },
      ],
    })
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(node)
    return () => {
      observer.disconnect()
      chart.dispose()
    }
  }, [device])

  return <div ref={host} className="h-36 w-full" role="img" aria-label={`${device.name}近 12 个读数`} />
}
