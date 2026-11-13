import { NavLink } from 'react-router-dom'
import { Icon } from './Icon'

const items = [
  { to: '/', label: '总控', icon: 'board' as const, end: true },
  { to: '/canvas', label: '画布', icon: 'flow' as const, end: false },
  { to: '/chat', label: '对话', icon: 'chat' as const, end: false },
  { to: '/tasks', label: '任务', icon: 'tasks' as const, end: false },
  { to: '/report', label: '报告', icon: 'report' as const, end: false },
  { to: '/settings', label: '设置', icon: 'settings' as const, end: false },
]

export function Sidebar({ open, onNavigate, onStart }: { open: boolean; onNavigate: () => void; onStart: () => void }) {
  return (
    <aside
      className={`no-print fixed inset-y-0 left-0 z-30 flex w-[220px] flex-col border-r border-[#ECEEF2] bg-panel transition-transform duration-200 md:static md:z-auto md:translate-x-0 ${
        open ? 'translate-x-0' : '-translate-x-full'
      }`}
    >
      <div className="flex h-16 items-center gap-2 px-4">
        <span className="sr-only">知秋</span>
        <span className="relative grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#173026] text-sm text-white" aria-hidden="true">
          知
          <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-[#E4B423]" />
        </span>
        <span className="text-base text-paper">知秋</span>
      </div>
      <div className="px-3">
        <button
          type="button"
          className="flex h-11 w-full items-center justify-center gap-1 rounded-btn bg-tea text-base text-white hover:bg-teaHover active:bg-teaPress"
          onClick={onStart}
        >
          + 开始巡园
        </button>
      </div>
      <nav className="mt-3 flex flex-1 flex-col gap-1 px-3" aria-label="页面">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              `flex min-h-11 items-center gap-3 rounded-xl px-3 py-2 text-[20px] font-medium leading-[1.3] ${
                isActive ? 'bg-panel2 text-tea' : 'text-dim hover:bg-[#F7F8FA]'
              }`
            }
          >
            <span>
              <Icon name={item.icon} />
            </span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
