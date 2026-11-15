import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import { soilDay } from '../data/snapshot'

function labelsFor(count: number) {
  const step = Math.max(1, Math.round(24 / Math.max(count, 1)))
  return Array.from({ length: count }, (_, index) => {
    if (index === count - 1) return '现在'
    const back = (count - 1 - index) * step
    const hour = (new Date().getHours() - back + 48) % 24
    return `${hour.toString().padStart(2, '0')}:00`
  })
}

export function SoilChart({ values = soilDay }: { values?: number[] }) {
  const host = useRef<HTMLDivElement>(null)
  const points = values.length > 1 ? values : soilDay

  useEffect(() => {
    const node = host.current
    if (!node) return
    const chart = echarts.init(node, undefined, { renderer: 'canvas' })
    chart.setOption({
      backgroundColor: 'transparent',
      animationDuration: 500,
      grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#FFFFFF',
        borderColor: '#E3EBE6',
        textStyle: { color: '#1D2129', fontFamily: 'PingFang SC, Noto Sans SC, sans-serif', fontSize: 14 },
        valueFormatter: (value: number) => `${value.toFixed(1)}%`,
      },
      xAxis: {
        type: 'category',
        data: labelsFor(points.length),
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#E3EBE6' } },
        axisTick: { show: false },
        axisLabel: {
          color: '#86909C',
          fontFamily: 'DIN, DIN Alternate, sans-serif',
          fontSize: 12,
          interval: Math.max(1, Math.round(points.length / 6)),
        },
      },
      yAxis: {
        type: 'value',
        min: (value: { min: number }) => Math.floor(Math.min(value.min, 38) - 2),
        max: (value: { max: number }) => Math.ceil(Math.max(value.max, 50) + 2),
        splitLine: { lineStyle: { color: '#E7EEE9' } },
        axisLabel: {
          color: '#86909C',
          fontFamily: 'DIN, DIN Alternate, sans-serif',
          fontSize: 12,
          formatter: '{value}%',
        },
      },
      series: [
        {
          type: 'line',
          name: '土壤湿度',
          data: points,
          smooth: 0.25,
          symbol: 'none',
          lineStyle: { color: '#1F7A45', width: 2.5 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(31, 122, 69, 0.22)' },
              { offset: 1, color: 'rgba(31, 122, 69, 0)' },
            ]),
          },
          markLine: {
            silent: true,
            symbol: 'none',
            data: [
              {
                yAxis: 40,
                label: {
                  formatter: '缺水线 40%',
                  color: '#8A6414',
                  fontFamily: 'PingFang SC, Noto Sans SC, sans-serif',
                  fontSize: 12,
                  position: 'insideStartTop',
                },
                lineStyle: { color: '#E4B423', type: 'dashed', width: 1 },
              },
            ],
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
  }, [points])

  return <div ref={host} className="h-[280px] w-full xl:h-full xl:min-h-[280px]" role="img" aria-label="近 24 小时土壤湿度曲线" />
}
