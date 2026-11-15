import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'
import type { PatrolRound } from '../data/patrolReport'

/**
 * 湿度轨迹：浇水前基线 → 每一轮复测。
 *
 * 以前这里写死样例的 38.5 → 45 → 57，报告页切到真实 run 时曲线还是那三个假点，
 * 页面上数字和线对不上。现在按当前 run 的轮次算，Y 轴跟着数据缩放
 * （真实基线可能 30 出头，两轮也可能都不到 55，写死 30–70 会把点压扁）。
 */
export function ReportTrend({ rounds }: { rounds: PatrolRound[] }) {
  const host = useRef<HTMLDivElement>(null)
  const labels = ['浇水前', ...rounds.map((round) => `第 ${round.round} 轮`)]
  const points = [rounds[0]?.baseline ?? null, ...rounds.map((round) => round.measured)]
  const numeric = points.filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  const min = Math.max(0, Math.floor(Math.min(...numeric, 55) - 5))
  const max = Math.min(100, Math.ceil(Math.max(...numeric, 65) + 5))
  const aria = points
    .map((value, index) => `${labels[index]} ${value === null ? '未测到' : `${value.toFixed(1)}%`}`)
    .join('，')

  useEffect(() => {
    const node = host.current
    if (!node) return
    const chart = echarts.init(node, undefined, { renderer: 'canvas' })
    chart.setOption({
      backgroundColor: 'transparent',
      animationDuration: 1200,
      animationEasing: 'cubicOut',
      grid: { left: 8, right: 20, top: 28, bottom: 4, containLabel: true },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#FFFFFF',
        borderColor: '#E3EBE6',
        textStyle: { color: '#1D2129', fontFamily: 'PingFang SC, Noto Sans SC, sans-serif' },
        valueFormatter: (value: number) => `${Number(value).toFixed(1)}%`,
      },
      xAxis: {
        type: 'category',
        data: labels,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#E3EBE6' } },
        axisTick: { show: false },
        axisLabel: { color: '#86909C', fontFamily: 'PingFang SC, Noto Sans SC, sans-serif', fontSize: 12 },
      },
      yAxis: {
        type: 'value',
        min,
        max,
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
              fontFamily: 'PingFang SC, Noto Sans SC, sans-serif',
              fontSize: 12,
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
    // 换 run / 换轮次要重画：只挂载一次的话切到两轮 run 曲线还是上一轮的
  }, [aria, labels.join('|'), min, max])

  return <div ref={host} className="chart-rise h-[280px] w-full" role="img" aria-label={`土壤湿度：${aria}`} />
}
