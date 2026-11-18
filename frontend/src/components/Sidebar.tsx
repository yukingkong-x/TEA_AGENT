import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { navItems, type NavItem } from '../data/nav'
import { Icon } from './Icon'

type Props = {
  open: boolean
  onNavigate: () => void
  onStart: () => void
  onAsk: () => void
}

/**
 * 侧边栏：图标 + 文字，圆角胶囊导航。
 *
 * 高亮不是每个 item 自己上 `bg-*`，而是**一块共用的玻璃胶囊**在 item 之间滑动：
 * - 位置/宽高由 rAF 弹簧驱动（不是 CSS transition），所以能带一点回弹；
 * - 移动中按速度沿运动轴拉长、另一轴轻微压扁，到位自然收回；
 * - 胶囊边缘用「白色内描边 + 极淡外环」做出细高光，底是半透明玻璃。
 *
 * 为什么不做两项各自的 crossfade：两个胶囊同时存在会互相透视，
 * 看起来像两块脏玻璃叠在一起；共用一块才像 iOS 的分段控件。
 */
export function Sidebar({ open, onNavigate, onStart, onAsk }: Props) {
  const { pathname } = useLocation()
  const activeTo =
    navItems.find((item) => (item.end ? pathname === item.to : pathname.startsWith(item.to)))?.to ?? '/'

  const { navRef, pillRef, setItem } = usePill(activeTo)

  return (
    <aside
      className={`no-print fixed inset-y-0 left-0 z-30 flex w-[224px] flex-col border-r border-white/70 bg-white/78 backdrop-blur-2xl transition-transform duration-200 md:static md:z-auto md:mb-3 md:ml-3 md:mt-3 md:translate-x-0 md:rounded-[26px] md:border md:border-white/70 md:shadow-[0_10px_34px_-18px_rgba(22,28,45,0.22)] ${
        open ? 'translate-x-0' : '-translate-x-full'
      }`}
      aria-label="主导航"
    >
      {/* 品牌 */}
      <div className="flex h-16 shrink-0 items-center gap-2.5 px-4">
        <span className="relative grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[#173026] text-base text-white">
          茶
          <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-[#E4B423]" />
        </span>
        <span className="min-w-0">
          <span className="block truncate text-[15px] font-semibold leading-tight text-paper">茶博士</span>
          <span className="block truncate text-[11px] leading-tight text-mute">茶园多智能体</span>
        </span>
      </div>

      {/* 两个高频动作：开始巡园是主动作，问 AI 是次动作 */}
      <div className="flex shrink-0 flex-col gap-2 px-3 pb-3">
        <button
          type="button"
          onClick={onStart}
          className="flex h-10 items-center gap-2 rounded-full bg-tea px-3 text-sm text-white shadow-[0_6px_16px_rgba(31,122,69,0.18)] transition-colors hover:bg-teaHover active:bg-teaPress"
        >
          <Icon name="plus" width={18} height={18} variant="current" />
          开始巡园
        </button>
        <button
          type="button"
          onClick={onAsk}
          className="flex h-10 items-center gap-2 rounded-full border border-line px-3 text-sm text-dim transition-colors hover:border-tea/40 hover:text-tea"
        >
          <Icon name="spark" width={18} height={18} variant="current" />
          问 AI
          <kbd className="num ml-auto rounded-md bg-[#F4F6F5] px-1.5 py-0.5 text-[10px] leading-none text-mute">
            Ctrl K
          </kbd>
        </button>
      </div>

      <Hairline />

      {/* 导航：玻璃胶囊在这一层里滑动，item 都压在它上面 */}
      <nav
        ref={navRef}
        className="relative flex flex-1 flex-col gap-1 overflow-y-auto px-3 py-2"
        aria-label="页面"
      >
        <span ref={pillRef} className="nav-pill" aria-hidden="true" />
        {renderGroups({ activeTo, setItem, onNavigate })}
      </nav>
    </aside>
  )
}

function renderGroups({
  activeTo,
  setItem,
  onNavigate,
}: {
  activeTo: string
  setItem: (to: string, el: HTMLAnchorElement | null) => void
  onNavigate: () => void
}) {
  const groups: Array<NavItem['group']> = ['monitor', 'collab', 'system']
  const nodes: ReactNode[] = []
  groups.forEach((group, index) => {
    if (index > 0) nodes.push(<Hairline key={`hairline-${group}`} />)
    navItems
      .filter((item) => item.group === group)
      .forEach((item) =>
        nodes.push(
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            ref={(el) => setItem(item.to, el)}
            aria-current={activeTo === item.to ? 'page' : undefined}
            className={({ isActive }) =>
              `group relative z-10 flex h-11 shrink-0 items-center gap-3 rounded-full px-3 text-[15px] leading-none transition-colors duration-200 ${
                isActive ? 'font-medium text-tea' : 'text-dim hover:bg-[#F6F8F7] hover:text-tea'
              }`
            }
          >
            <span className="grid h-5 w-5 shrink-0 place-items-center">
              <Icon name={item.icon} width={20} height={20} />
            </span>
            <span className="truncate">{item.label}</span>
          </NavLink>,
        ),
      )
  })
  return nodes
}

function Hairline() {
  return <div className="mx-3 my-2 h-px shrink-0 bg-[#EFF2F0]" aria-hidden="true" />
}

/* ------------------------------------------------------------ 玻璃胶囊 */

type PillState = {
  x: number
  y: number
  w: number
  h: number
  vx: number
  vy: number
  vw: number
  vh: number
  ready: boolean
}

/**
 * 共用滑动胶囊。
 *
 * 弹簧是手调的：K=420 / D=30（阻尼比约 0.73）→ 200px 位移约 380ms 到位，
 * 冲过头约 4% 再弹回，是「一点回弹」而不是晃荡。D 别低于 22，
 * 否则会变成果冻，看起来像掉帧。
 */
function usePill(activeTo: string) {
  const navRef = useRef<HTMLElement | null>(null)
  const pillRef = useRef<HTMLSpanElement | null>(null)
  const items = useRef(new Map<string, HTMLAnchorElement>())
  const state = useRef<PillState>({ x: 0, y: 0, w: 0, h: 0, vx: 0, vy: 0, vw: 0, vh: 0, ready: false })
  const [tickKey, setTickKey] = useState(0)

  const setItem = useCallback((to: string, el: HTMLAnchorElement | null) => {
    if (el) items.current.set(to, el)
    else items.current.delete(to)
  }, [])

  const paint = useCallback(() => {
    const pill = pillRef.current
    const s = state.current
    if (!pill) return
    pill.style.width = `${s.w}px`
    pill.style.height = `${s.h}px`
    // 沿运动方向拉长、另一方向轻微压扁：速度越大越明显，停下自然回到 1
    const stretch = Math.min(0.09, Math.abs(s.vy) / 2600)
    const sy = 1 + stretch
    const sx = 1 - stretch * 0.45
    pill.style.transform = `translate3d(${s.x}px, ${s.y}px, 0) scale(${sx}, ${sy})`
    pill.style.opacity = s.ready ? '1' : '0'
  }, [])

  useEffect(() => {
    const el = items.current.get(activeTo)
    if (!el) return
    const target = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight }
    const s = state.current
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    if (!s.ready || reduce) {
      Object.assign(s, target, { vx: 0, vy: 0, vw: 0, vh: 0, ready: true })
      paint()
      return
    }

    const K = 420
    const D = 30
    let raf = 0
    let last = performance.now()

    const step = (now: number) => {
      const dt = Math.min(0.032, (now - last) / 1000)
      last = now
      s.vx += (K * (target.x - s.x) - D * s.vx) * dt
      s.vy += (K * (target.y - s.y) - D * s.vy) * dt
      s.vw += (K * (target.w - s.w) - D * s.vw) * dt
      s.vh += (K * (target.h - s.h) - D * s.vh) * dt
      s.x += s.vx * dt
      s.y += s.vy * dt
      s.w += s.vw * dt
      s.h += s.vh * dt
      paint()

      const settled =
        Math.abs(target.x - s.x) < 0.4 &&
        Math.abs(target.y - s.y) < 0.4 &&
        Math.abs(target.w - s.w) < 0.4 &&
        Math.abs(target.h - s.h) < 0.4 &&
        Math.abs(s.vx) < 6 &&
        Math.abs(s.vy) < 6
      if (settled) {
        Object.assign(s, target, { vx: 0, vy: 0, vw: 0, vh: 0 })
        paint()
        return
      }
      raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [activeTo, tickKey, paint])

  // 窗口尺寸变化 / 字体加载完成后重新对位（对不上会看到胶囊与文字错开半格）
  useEffect(() => {
    const bump = () => setTickKey((key) => key + 1)
    window.addEventListener('resize', bump)
    const timer = window.setTimeout(bump, 400)
    return () => {
      window.removeEventListener('resize', bump)
      window.clearTimeout(timer)
    }
  }, [])

  return { navRef, pillRef, setItem }
}
