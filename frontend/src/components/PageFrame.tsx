import type { ReactNode } from 'react'
import { useShell } from '../shell/ShellContext'
import { Clock } from './Clock'

export function PageFrame({
  title,
  fill = false,
  children,
}: {
  title: string
  fill?: boolean
  children: ReactNode
}) {
  return (
    <div className="page-enter flex min-h-0 flex-1 flex-col">
      <header className="mb-3 flex shrink-0 items-center justify-between gap-3">
        <h1 className="text-paper">{title}</h1>
        <StatusCluster />
      </header>
      {/*
       * 这里刻意不再铺一层白色面板：页面里的每一块内容自己就是玻璃卡片，
       * 底色交给 App 的环境光。留这层只为了管滚动（fill 模式还要管 flex）。
       */}
      <div
        className={`min-h-0 flex-1 rounded-[16px] ${
          fill ? 'flex flex-col overflow-hidden' : 'overflow-auto'
        }`}
      >
        {children}
      </div>
    </div>
  )
}

function StatusCluster() {
  const { mode, link } = useShell()
  const mock = mode === 'mock'
  const online = link === 'open'
  return (
    <div className="no-print flex shrink-0 items-center gap-3 text-xs leading-none text-mute">
      <span className={`num rounded-btn px-2 py-0.5 text-xs ${mock ? 'bg-panel2 text-tea' : 'bg-paper text-white'}`}>
        {mock ? 'MOCK' : 'REAL'}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${online ? 'bg-tea' : 'bg-mute'}`} aria-hidden="true" />
        {online ? '已连接' : '未连接'}
      </span>
      <span className="hidden sm:inline">
        <Clock />
      </span>
    </div>
  )
}
