import { agents } from '../data/snapshot'

export function ChatPage() {
  return (
    <div className="page-enter -mt-3 mx-auto flex min-h-[640px] w-full max-w-[1360px] flex-1 flex-col gap-4 lg:h-full lg:min-h-0">
      <header className="shrink-0">
        <h1 className="text-[28px] font-medium leading-none">对话</h1>
        <p className="mt-2 text-sm text-dim">本轮还没有发言。</p>
      </header>
      <div className="grid min-h-0 flex-1 items-stretch gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
        <section className="flex min-h-[320px] flex-col rounded-card border border-line bg-panel lg:min-h-0">
          <div className="flex flex-1 items-center justify-center px-6 py-16">
            <p className="max-w-sm text-center text-base text-dim">开始巡园后，七个智能体的发言会按时间出现在这里。</p>
          </div>
        </section>
        <aside className="min-h-0 overflow-auto rounded-card border border-line bg-panel p-4">
          <h2 className="flex items-center gap-2 px-2 text-base font-medium">
            <span className="h-2 w-2 rounded-full bg-[#E4B423]" aria-hidden="true" />
            本轮成员
          </h2>
          <ul className="mt-3 grid gap-1">
            {agents.map((agent) => (
              <li key={agent.key} className="flex items-center gap-3 rounded-btn px-2 py-2">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink text-sm text-tea">{agent.mark}</span>
                <span className="min-w-0">
                  <span className="block text-sm text-paper">{agent.name}</span>
                  <span className="block truncate text-[13px] text-dim">{agent.job}</span>
                </span>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  )
}
