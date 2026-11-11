import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import { patrolRounds } from '../data/patrolReport'

const labels = ['浇水前', '第 1 轮', '第 2 轮']
const points = [patrolRounds[0].baseline, patrolRounds[0].measured, patrolRounds[1].measured]

export function ReportTrend() {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const node = host.current
    if (!node) return
    const chart = echarts.init(node, undefined, { renderer: 'canvas' })
    chart.setOption({
      backgroundColor: 'transparent',
      animationDuration: 500,
      grid: { left: 8, right: 20, top: 28, bottom: 4, containLabel: true },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#FFFFFF',
        borderColor: '#E3EBE6',
        textStyle: { color: '#17211B', fontFamily: 'Noto Sans SC' },
        valueFormatter: (value: number) => `${value.toFixed(1)}%`,
      },
      xAxis: {
        type: 'category',
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#E3EBE6' } },
        axisTick: { show: false },
        axisLabel: { color: '#66756C', fontFamily: 'Noto Sans SC' },
      },
      yAxis: {
        type: 'value',
        min: 30,
        max: 70,
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
          data: points,
          smooth: 0.35,
          symbol: 'circle',
          symbolSize: 10,
          itemStyle: { color: '#FFFFFF', borderColor: '#1F7A45', borderWidth: 2 },
          lineStyle: { color: '#1F7A45', width: 2.5 },
          areaStyle: {
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: 'rgba(31, 122, 69, 0.22)' },
              { offset: 1, color: 'rgba(31, 122, 69, 0)' },
            ]),
          },
          markArea: {
            silent: true,
            itemStyle: { color: 'rgba(31, 122, 69, 0.08)' },
            label: {
              show: true,
              position: 'insideTopRight',
              color: '#1F7A45',
              fontFamily: 'Noto Sans SC',
              formatter: '目标 55%–65%',
            },
            data: [[{ yAxis: 55 }, { yAxis: 65 }]],
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

  return (
    <div
      ref={host}
      className="h-[280px] w-full"
      role="img"
      aria-label="土壤湿度从浇水前 38.5% 到第 1 轮 45.0%，再到第 2 轮 57.0%，落入目标 55% 到 65%"
    />
  )
}
