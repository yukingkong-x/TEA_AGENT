import { useId, type SVGProps } from 'react'

type IconName =
  | 'board'
  | 'flow'
  | 'chat'
  | 'tasks'
  | 'report'
  | 'settings'
  | 'menu'
  | 'close'
  | 'spark'
  | 'search'
  | 'enter'
  | 'plus'

const paths: Record<IconName, string> = {
  board: 'M4 4h6v6H4V4zm10 0h6v6h-6V4zM4 14h6v6H4v-6zm10 2h6v4h-6v-4z',
  flow: 'M5 7h4v4H5V7zm10 0h4v4h-4V7zM7 11v2h10v-2M12 13v4m-5 0h10v4H7v-4z',
  chat: 'M5 6h14v9H8l-3 3V6z',
  tasks: 'M6 6h12M6 12h12M6 18h8',
  report: 'M12 5a7 7 0 1 1 0 14 7 7 0 0 1 0-14zm0 3v4l3 2',
  settings: 'M4 8h10M18 8h2M4 16h2M10 16h10M14 6v4M8 14v4',
  menu: 'M5 7h14M5 12h14M5 17h14',
  close: 'M7 7l10 10M17 7 7 17',
  // 问 AI：四点星芒，比「魔法棒」干净，也不会让人以为是一键生成
  spark: 'M12 4.5l1.6 4.3 4.4 1.7-4.4 1.7L12 16.5l-1.6-4.3L6 10.5l4.4-1.7L12 4.5zM18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8z',
  search: 'M11 5a6 6 0 1 1 0 12 6 6 0 0 1 0-12zm4.6 10.6L20 20',
  enter: 'M9 6v6h8m-3-3 3 3-3 3',
  plus: 'M12 5v14M5 12h14',
}

type Props = SVGProps<SVGSVGElement> & {
  name: IconName
  /**
   * gradient（默认）：茶绿三段渐变描边，细、圆头，像一根根磨圆的细柱
   * current：跟随 currentColor，用于绿底白图标、以及灰色提示箭头这类不该抢色的地方
   */
  variant?: 'gradient' | 'current'
}

export function Icon({ name, variant = 'gradient', strokeWidth = 1.5, ...props }: Props) {
  // useId 保证每个实例的渐变 id 唯一：同一页面几十个图标共用同一个 id 时，
  // 浏览器只认第一个定义，遇到条件渲染就会整片图标「掉色」。
  const gid = `icon-grad-${useId().replace(/[:]/g, '')}`

  return (
    <svg
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke={variant === 'gradient' ? `url(#${gid})` : 'currentColor'}
      strokeWidth={strokeWidth}
      aria-hidden="true"
      {...props}
    >
      {variant === 'gradient' ? (
        <defs>
          <linearGradient id={gid} x1="3.5" y1="2.5" x2="20.5" y2="21.5" gradientUnits="userSpaceOnUse">
            <stop offset="0%" stopColor="#6ACB95" />
            <stop offset="46%" stopColor="#2E9E5D" />
            <stop offset="100%" stopColor="#14603C" />
          </linearGradient>
        </defs>
      ) : null}
      <path d={paths[name]} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
