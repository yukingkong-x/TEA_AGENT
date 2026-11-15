import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { Device } from '../data/snapshot'

/** 历史时间戳 → 横轴标签（HH:mm） */
function stampLabel(ts: string) {
  // 后端给的是 "2026-05-01 10:00:00"（空格分隔），iOS Safari 解不了
  const date = new Date(ts.replace(' ', 'T'))
  if (Number.isNaN(date.getTime())) return ts
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

export function DeviceChart({
  device,
  values,
  stamps,
}: {
  device: Device
  /** 有后端历史就用它，没有就退回本会话攒的点 */
  values?: number[]
  /** 历史点的原始时间戳，用来做横轴 */
  stamps?: string[]
}) {
  const host = useRef<HTMLDivElement>(null)
  const series = values?.length ? values : device.series
  const labels = stamps?.length === series.length ? stamps.map(stampLabel) : series.map((_, index) => `${index + 1}`)

  useEffect(() => {
    const node = host.current
    if (!node) return
    const chart = echarts.init(node, undefined, { renderer: 'canvas' })
    const flat = series.every((point) => point === series[0])
    chart.setOption({
      backgroundColor: 'transparent',
      animationDuration: 400,
      grid: { left: 40, right: 10, top: 16, bottom: 24 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#FFFFFF',
        borderColor: '#E3EBE6',
        textStyle: { color: '#1D2129', fontSize: 12 },
        valueFormatter: (value: number) => `${value}${device.unit}`,
      },
      xAxis: {
        type: 'category',
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#E3EBE6' } },
        axisTick: { show: false },
        axisLabel: { color: '#86909C', fontSize: 11, interval: Math.max(0, Math.floor(labels.length / 5) - 1) },
      },
      yAxis: {
        type: 'value',
        // 一串完全相同的读数（传感器卡住）时给 0-1 硬边界，避免 ECharts 画出诡异的自动区间
        min: flat ? 0 : undefined,
        max: flat ? 1 : undefined,
        scale: !flat,
        splitLine: { lineStyle: { color: '#EFEAE3' } },
        axisLabel: {
          color: '#86909C',
          fontSize: 12,
          fontFamily: 'DIN, DIN Alternate, sans-serif',
          formatter: (value: number) => `${value}`,
        },
      },
      series: [
        {
          type: 'line',
          data: series,
          smooth: 0.2,
          symbol: labels.length > 80 ? 'none' : 'circle',
          symbolSize: 4,
          lineStyle: { color: '#1F7A45', width: 2 },
          itemStyle: { color: '#1F7A45' },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(31, 122, 69, 0.18)' },
              { offset: 1, color: 'rgba(31, 122, 69, 0)' },
            ]),
          },
        },
      ],
    })
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(node)
    return () => {
      observer.disconnect()
      chart.dispose()
    }
  }, [device.unit, labels, series])

  return <div ref={host} className="h-36 w-full" role="img" aria-label={`${device.name}近 24 小时${device.seriesName}曲线`} />
}
