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
        borderColor: '#E4DDD4',
        textStyle: { color: '#1A1A1A', fontFamily: 'Noto Sans SC' },
        valueFormatter: (value: number) => `${value.toFixed(1)}%`,
      },
      xAxis: {
        type: 'category',
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#E4DDD4' } },
        axisTick: { show: false },
        axisLabel: {
          color: '#6F675F',
          fontFamily: 'DIN Alternate, ui-monospace, monospace',
          interval: 3,
        },
      },
      yAxis: {
        type: 'value',
        min: 30,
        max: 55,
        splitLine: { lineStyle: { color: '#EFEAE3' } },
        axisLabel: {
          color: '#6F675F',
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
          lineStyle: { color: '#2F7A4A', width: 2 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(47, 122, 74, 0.2)' },
              { offset: 1, color: 'rgba(47, 122, 74, 0)' },
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
                  color: '#9A5B12',
                  fontFamily: 'Noto Sans SC',
                  position: 'insideStartTop',
                },
                lineStyle: { color: '#C47B2B', type: 'dashed', width: 1 },
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
