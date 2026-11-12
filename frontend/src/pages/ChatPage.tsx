import { PageFrame } from '../components/PageFrame'
import { agents } from '../data/snapshot'

export function ChatPage() {
  return (
    <PageFrame title="对话" fill>
    <div className="grid h-full min-h-[520px] lg:grid-cols-[minmax(0,1fr)_260px]">
        <section className="flex min-h-[280px] items-center justify-center border-b border-[#EEF0F3] px-6 lg:border-b-0 lg:border-r">
            <p className="max-w-sm text-center text-xs leading-normal text-mute">开始巡园后，七个智能体的发言会按时间出现在这里。</p>
        </section>
        <aside className="min-h-0 overflow-auto p-4">
          <h2 className="px-2 text-paper">本轮成员</h2>
          <ul className="mt-3 grid gap-1">
            {agents.map((agent) => (
              <li key={agent.key} className="flex items-center gap-3 rounded-btn px-2 py-2">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink text-sm text-tea">{agent.mark}</span>
                <span className="min-w-0">
                  <span className="block text-sm leading-normal text-paper">{agent.name}</span>
                  <span className="block truncate text-xs leading-none text-mute">{agent.job}</span>
                </span>
              </li>
            ))}
          </ul>
        </aside>
    </div>
    </PageFrame>
  )
}
