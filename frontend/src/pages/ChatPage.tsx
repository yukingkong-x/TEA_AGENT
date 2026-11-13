import { useMemo, useState } from 'react'
import { PageFrame } from '../components/PageFrame'
import { chatThreads, type ChatMessage, type Citation, type ToolCall } from '../data/chat'
import { patrolRuns } from '../data/patrolReport'
import { agents } from '../data/snapshot'

export function ChatPage() {
  const [runId, setRunId] = useState(patrolRuns[0].id)
  const messages = chatThreads[runId] ?? []
  const speaker = messages[messages.length - 1]?.agentKey

  return (
    <PageFrame title="对话" fill>
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex shrink-0 items-center gap-3 border-b border-[#EEF0F3] px-5 py-3">
          <label className="flex items-center gap-3 text-sm text-dim" htmlFor="chat-run">
            本次巡园
            <select
              id="chat-run"
              value={runId}
              onChange={(event) => setRunId(event.target.value)}
              className="h-11 rounded-btn border border-line bg-panel px-3 text-base text-paper"
            >
              {patrolRuns.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_240px]">
          <div className="min-h-0 overflow-auto px-4 py-4 sm:px-5">
            <div className="grid gap-4">
              {messages.map((message) => (
                <Message key={message.id} message={message} />
              ))}
            </div>
          </div>
          <aside className="min-h-0 overflow-auto border-t border-[#EEF0F3] p-4 lg:border-l lg:border-t-0">
            <h2 className="px-2 text-paper">本轮成员</h2>
            <ul className="mt-3 grid gap-1">
              {agents.map((agent) => {
                const active = agent.key === speaker
                return (
                  <li key={agent.key} className={`flex items-center gap-3 rounded-btn px-2 py-2 ${active ? 'bg-panel2' : ''}`}>
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-full text-lg ${active ? 'bg-panel ring-2 ring-tea' : 'bg-ink'}`} aria-hidden="true">
                      {agent.avatar}
                    </span>
                    <span className="min-w-0">
                      <span className={`block text-sm leading-normal ${active ? 'text-tea' : 'text-paper'}`}>{agent.name}</span>
                      <span className="block truncate text-xs leading-none text-mute">{agent.job}</span>
                    </span>
                  </li>
                )
              })}
            </ul>
          </aside>
        </div>
      </div>
    </PageFrame>
  )
}

function Message({ message }: { message: ChatMessage }) {
  const agent = agents.find((item) => item.key === message.agentKey)
  const denied = message.calls?.some((call) => call.result.status === 'denied') ?? false
  return (
    <article className="flex items-start gap-3">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-ink text-lg" aria-hidden="true">
        {agent?.avatar}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-sm text-paper">{agent?.name}</span>
          <time className="num text-xs text-mute">{message.at}</time>
        </div>
        <div className="mt-1 max-w-3xl overflow-hidden rounded-2xl bg-[#F7F8FA]">
          {message.degraded ? <p className="bg-[#FFF4CC] px-3 py-2 text-sm text-[#8A6414]">⚠️ 模型降级输出</p> : null}
          <p className="px-3 py-2 text-sm leading-normal text-paper">
            <RichText text={message.content} citations={message.citations} />
          </p>
          {denied ? <p className="bg-[#F2F3F5] px-3 py-2 text-sm text-dim">⛔ 权限不足：send_device_cmd（已拦截）</p> : null}
        </div>
        {message.calls?.map((call) => (
          <ToolBlock key={call.name} call={call} />
        ))}
      </div>
    </article>
  )
}

function RichText({ text, citations }: { text: string; citations?: Citation[] }) {
  const parts = useMemo(() => text.split(/(\[\d+\])/g), [text])
  return parts.map((part, index) => {
    const match = /^\[(\d+)\]$/.exec(part)
    if (!match) return <span key={index}>{part}</span>
    const cite = citations?.find((item) => item.id === match[1])
    return (
      <span key={index} className="group relative inline-block">
        <span className="cursor-help text-tea underline decoration-tea underline-offset-2">[{match[1]}]</span>
        {cite ? (
          <span className="pointer-events-none absolute left-0 top-full z-10 mt-1 hidden w-56 rounded-lg bg-paper px-2 py-2 text-xs leading-normal text-white shadow group-hover:block">
            {cite.excerpt}
          </span>
        ) : null}
      </span>
    )
  })
}

function ToolBlock({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-2 max-w-3xl">
      <button type="button" className="text-sm text-tea" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        {open ? '收起' : '展开'} {call.name}
      </button>
      {open ? (
        <pre className="num mt-2 overflow-auto rounded-lg bg-[#F7F8FA] p-3 text-xs leading-normal text-dim">
          {JSON.stringify({ args: call.args, result: call.result }, null, 2)}
        </pre>
      ) : null}
    </div>
  )
}
