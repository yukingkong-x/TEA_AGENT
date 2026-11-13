import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

function Gauge({ value, label, height }: { value: number; label: string; height: number }) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const node = host.current
    if (!node) return
    const chart = echarts.init(node)
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    chart.setOption({
      animationDuration: reduce ? 0 : 1100,
      animationEasing: 'cubicOut',
      series: [
        {
          type: 'gauge',
          startAngle: 90,
          endAngle: -270,
          min: 0,
          max: 100,
          radius: '86%',
          progress: {
            show: true,
            width: 18,
            roundCap: true,
            itemStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 1, 1, [
                { offset: 0, color: '#8FCB9E' },
                { offset: 1, color: '#1F7A45' },
              ]),
            },
          },
          axisLine: { lineStyle: { width: 18, color: [[1, '#E7EEE9']] } },
          pointer: { show: false },
          axisTick: { show: false },
          splitLine: { show: false },
          axisLabel: { show: false },
          detail: { show: false },
          data: [{ value }],
        },
      ],
    })
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
    }
  }, [value])

  return (
    <div className="relative" style={{ height }}>
      <div ref={host} className="h-full w-full" />
      <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
        <div>
          <span className="num block text-[28px] font-semibold leading-none text-paper">{value.toFixed(2)}%</span>
          <span className="mt-1 block text-xs leading-none text-mute">{label}</span>
        </div>
      </div>
    </div>
  )
}

export function ConfidenceGauge({ value, caption }: { value: number; caption: string }) {
  return <Gauge value={value} label={caption} height={220} />
}
