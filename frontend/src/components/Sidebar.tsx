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

export function Sidebar({ open, onNavigate }: { open: boolean; onNavigate: () => void }) {
  return (
    <aside
      className={`fixed inset-y-0 left-0 z-30 flex w-[240px] flex-col bg-panel shadow-[0_16px_40px_rgba(23,48,38,0.08)] transition-transform duration-200 md:static md:z-auto md:my-3 md:ml-3 md:h-auto md:w-[84px] md:translate-x-0 md:rounded-[28px] md:border md:border-line lg:w-[220px] ${
        open ? 'translate-x-0' : '-translate-x-full'
      }`}
    >
      <div className="flex h-20 items-center gap-2 px-4 lg:px-5">
        <span className="sr-only">知秋</span>
        <span className="relative grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[#173026] text-sm text-white" aria-hidden="true">
          知
          <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-white bg-[#E4B423]" />
        </span>
        <span className="text-lg font-semibold tracking-tight text-paper md:hidden lg:inline">知秋</span>
      </div>
      <nav className="flex flex-1 flex-col gap-1 p-3" aria-label="页面">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            title={item.label}
            className={({ isActive }) =>
              `flex h-11 items-center gap-3 rounded-btn px-3 text-[15px] ${
                isActive ? 'bg-[#173026] text-white' : 'text-dim hover:bg-[#E7F3EA] hover:text-paper'
              }`
            }
          >
            {({ isActive }) => (
              <>
                <span className={isActive ? 'text-white' : 'text-tea'}>
                  <Icon name={item.icon} />
                </span>
                <span className="hidden max-md:inline lg:inline">{item.label}</span>
                <span className="sr-only max-md:hidden lg:hidden">{item.label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
