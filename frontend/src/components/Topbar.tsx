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
    <header className="flex h-16 shrink-0 items-center gap-3 border-b border-line bg-panel px-4 sm:px-6">
      <button type="button" className="btn btn-ghost h-11 w-11 px-0 md:hidden" aria-label="打开导航" onClick={onMenu}>
        <Icon name="menu" />
      </button>
      <span
        className={`num inline-flex h-7 items-center rounded-btn border px-2 text-xs font-medium tracking-wide ${
          mock ? 'border-tea/40 text-tea' : 'border-run/50 text-run'
        }`}
      >
        {mock ? 'MOCK' : 'REAL'}
      </span>
      <span className="inline-flex items-center gap-2 text-sm text-dim">
        <span className="h-2 w-2 rounded-full bg-mute" aria-hidden="true" />
        未连接
      </span>
      <div className="ml-auto flex items-center gap-3 sm:gap-4">
        <Clock />
        {pathname === '/' ? (
          <Button onClick={onStart} className="px-4 sm:px-5">
            开始巡园
          </Button>
        ) : null}
      </div>
    </header>
  )
}
