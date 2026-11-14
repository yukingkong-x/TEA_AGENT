/**
 * 【审阅用临时补丁 · 请勿提交】
 * 原分支 feature/frontend-dashboard 缺少此文件，MetricTile.tsx 引用它导致页面无法加载。
 * 这里按「数字从 0 缓动到目标值」的常规实现补一个，仅为了让本地预览能跑起来。
 * 队友 A 请把自己本地的 src/lib/useCountUp.ts 提交上来，然后删掉这个文件。
 */
import { useEffect, useState } from 'react'

export function useCountUp(target: number, duration = 900): number {
  const [value, setValue] = useState(0)

  useEffect(() => {
    if (!Number.isFinite(target)) {
      setValue(0)
      return
    }
    let frame = 0
    const startedAt = performance.now()

    const tick = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / duration)
      const eased = 1 - Math.pow(1 - progress, 3)
      setValue(target * eased)
      if (progress < 1) {
        frame = requestAnimationFrame(tick)
      }
    }

    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [target, duration])

  return value
}
