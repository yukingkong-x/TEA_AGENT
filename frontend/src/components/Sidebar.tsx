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
      className={`fixed inset-y-0 left-0 z-30 flex w-[232px] flex-col border-r border-line bg-panel transition-transform duration-200 md:static md:w-[76px] md:translate-x-0 lg:w-[232px] ${
        open ? 'translate-x-0' : '-translate-x-full'
      }`}
    >
      <div className="flex h-20 items-center px-4 lg:px-5">
        <span className="sr-only">知秋</span>
        <span className="font-serif text-[26px] leading-none text-paper" aria-hidden="true">
          知<span className="md:hidden lg:inline">秋</span>
        </span>
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
              `flex h-11 items-center gap-3 rounded-btn px-3 text-base ${
                isActive ? 'bg-ink text-paper' : 'text-dim hover:bg-ink hover:text-paper'
              }`
            }
          >
            {({ isActive }) => (
              <>
                <span className={isActive ? 'text-tea' : 'text-mute'}>
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
