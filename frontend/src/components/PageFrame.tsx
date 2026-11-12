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
      <div
        className={`min-h-0 flex-1 rounded-[16px] bg-panel shadow-[0_1px_2px_rgba(22,28,45,0.05)] ${
          fill ? 'flex flex-col overflow-hidden' : 'overflow-auto'
        }`}
      >
        {children}
      </div>
    </div>
  )
}

function StatusCluster() {
  const { mode } = useShell()
  const mock = mode === 'mock'
  return (
    <div className="flex shrink-0 items-center gap-3 text-xs leading-none text-mute">
      <span className={`num rounded-btn px-2 py-0.5 text-xs ${mock ? 'bg-panel2 text-tea' : 'bg-paper text-white'}`}>
        {mock ? 'MOCK' : 'REAL'}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full bg-mute" aria-hidden="true" />
        未连接
      </span>
      <span className="hidden sm:inline">
        <Clock />
      </span>
    </div>
  )
}
