import { useLocation } from 'react-router-dom'
import { useShell } from '../shell/ShellContext'
import { Button } from './Button'
import { Clock } from './Clock'
import { Icon } from './Icon'

type TopbarProps = {
  onMenu: () => void
  onStart: () => void
}

export function Topbar({ onMenu, onStart }: TopbarProps) {
  const { mode } = useShell()
  const { pathname } = useLocation()
  const mock = mode === 'mock'

  return (
    <header className="flex h-16 w-full min-w-0 items-center gap-2 px-3 sm:gap-3 sm:px-6">
      <button type="button" className="btn btn-ghost h-11 w-11 shrink-0 px-0 md:hidden" aria-label="打开导航" onClick={onMenu}>
        <Icon name="menu" />
      </button>
      <span
        className={`num inline-flex h-8 shrink-0 items-center rounded-btn px-3 text-xs font-medium tracking-wide ${
          mock ? 'bg-[#E5F6EA] text-tea' : 'bg-[#173026] text-white'
        }`}
      >
        {mock ? 'MOCK' : 'REAL'}
      </span>
      <span className="inline-flex min-w-0 items-center gap-2 text-sm text-dim">
        <span className="h-2 w-2 shrink-0 rounded-full bg-mute" aria-hidden="true" />
        <span className="hidden truncate sm:inline">未连接</span>
        <span className="sr-only sm:hidden">未连接</span>
      </span>
      <div className="ml-auto flex shrink-0 items-center gap-2 sm:gap-4">
        <span className="hidden md:inline">
          <Clock />
        </span>
        {pathname === '/' ? (
          <Button onClick={onStart} className="px-3 text-sm sm:px-5 sm:text-base">
            开始巡园
          </Button>
        ) : null}
      </div>
    </header>
  )
}
