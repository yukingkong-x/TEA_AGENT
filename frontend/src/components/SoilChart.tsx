import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import { soilDay } from '../data/snapshot'

const labels = soilDay.map((_, index) => {
  const hour = index.toString().padStart(2, '0')
  return index === soilDay.length - 1 ? '现在' : `${hour}:00`
})

export function SoilChart() {
  const host = useRef<HTMLDivElement>(null)

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
        textStyle: { color: '#1A1A1A', fontFamily: 'Noto Sans SC' },
        valueFormatter: (value: number) => `${value.toFixed(1)}%`,
      },
      xAxis: {
        type: 'category',
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#E3EBE6' } },
        axisTick: { show: false },
        axisLabel: {
          color: '#66756C',
          fontFamily: 'DIN Alternate, ui-monospace, monospace',
          interval: 3,
        },
      },
      yAxis: {
        type: 'value',
        min: 30,
        max: 55,
        splitLine: { lineStyle: { color: '#E7EEE9' } },
        axisLabel: {
          color: '#66756C',
          fontFamily: 'DIN Alternate, ui-monospace, monospace',
          formatter: '{value}%',
        },
      },
      series: [
        {
          type: 'line',
          name: '土壤湿度',
          data: soilDay,
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
                  fontFamily: 'Noto Sans SC',
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
  }, [])

  return <div ref={host} className="h-[280px] w-full xl:h-full xl:min-h-[280px]" role="img" aria-label="近 24 小时土壤湿度，从 46.8% 降到 38.5%" />
}
