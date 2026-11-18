/**
 * 磨砂玻璃卡片：整个控制台的基础容器。
 *
 * 三件事，全部是「轻」的，别加重：
 * 1. 材质：半透明白 + backdrop-blur，靠 App 里那层极淡的彩色光晕透出来；
 * 2. 悬停跟随光斑：`--mx/--my` 每帧写一次，伪元素画径向渐变，进卡片才显形；
 * 3. 轻微 3D 倾斜：最多 ±4°，鼠标一离开就回到平面。
 *
 * 注意：内容里有 ECharts / 抽屉 / 绝对定位下拉时把 `tilt` 关掉——
 * 3D 变换会让 canvas 重新采样变糊，也会让 fixed/absolute 的层级错位。
 */
import {
  useCallback,
  useEffect,
  useRef,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  type RefObject,
} from 'react'

type Props = {
  children: ReactNode
  className?: string
  /** 关闭 3D 倾斜，只保留玻璃与光斑 */
  tilt?: boolean
  /** 语义标签，默认 section */
  as?: 'section' | 'div' | 'article'
  /** 无障碍标签（玻璃卡片通常是区块，需要一个名字） */
  label?: string
}

/** 倾斜上限：±4°（用户明确要求「不超过 4 度」） */
const MAX_DEG = 4

export function GlassCard({ children, className = '', tilt = true, as = 'section', label }: Props) {
  const ref = useRef<HTMLElement | null>(null)
  const frame = useRef(0)
  const point = useRef({ x: 0, y: 0 })
  const fine = useRef(false)

  useEffect(() => {
    fine.current = window.matchMedia('(hover: hover) and (pointer: fine)').matches
    return () => {
      if (frame.current) cancelAnimationFrame(frame.current)
    }
  }, [])

  const paint = useCallback(() => {
    frame.current = 0
    const el = ref.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const { x, y } = point.current
    el.style.setProperty('--mx', `${x}px`)
    el.style.setProperty('--my', `${y}px`)
    if (!tilt || !fine.current || rect.width === 0 || rect.height === 0) return
    const rx = (0.5 - y / rect.height) * MAX_DEG * 2
    const ry = (x / rect.width - 0.5) * MAX_DEG * 2
    el.style.transform = `perspective(900px) rotateX(${rx.toFixed(2)}deg) rotateY(${ry.toFixed(2)}deg)`
  }, [tilt])

  const onPointerEnter = (event: ReactPointerEvent<HTMLElement>) => {
    if (event.pointerType !== 'mouse') return
    const rect = event.currentTarget.getBoundingClientRect()
    point.current = { x: event.clientX - rect.left, y: event.clientY - rect.top }
    event.currentTarget.classList.add('is-live')
    paint()
  }

  const onPointerMove = (event: ReactPointerEvent<HTMLElement>) => {
    if (event.pointerType !== 'mouse') return
    const rect = event.currentTarget.getBoundingClientRect()
    point.current = { x: event.clientX - rect.left, y: event.clientY - rect.top }
    if (!frame.current) frame.current = requestAnimationFrame(paint)
  }

  const onPointerLeave = (event: ReactPointerEvent<HTMLElement>) => {
    const el = event.currentTarget
    if (frame.current) {
      cancelAnimationFrame(frame.current)
      frame.current = 0
    }
    el.classList.remove('is-live')
    el.style.transform = ''
  }

  const Tag = as as 'section'
  return (
    <Tag
      ref={ref as RefObject<HTMLElement>}
      aria-label={label}
      className={`glass-card ${className}`}
      onPointerEnter={onPointerEnter}
      onPointerMove={onPointerMove}
      onPointerLeave={onPointerLeave}
    >
      {children}
    </Tag>
  )
}
