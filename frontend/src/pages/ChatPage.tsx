import { useMemo, useState } from 'react'
import { PageFrame } from '../components/PageFrame'
import { chatThreads, type Citation, type ToolCall } from '../data/chat'
import { patrolRuns } from '../data/patrolReport'
import { agents } from '../data/snapshot'
import { useAgentMessages, type UiMessage } from '../hooks/useAgentMessages'

const fallbackLabel = patrolRuns[0].name

export function ChatPage() {
  const [runId, setRunId] = useState(patrolRuns[0].id)
  const fallback = useMemo(() => chatThreads[runId] ?? [], [runId])
  const { messages, source, runLabel, reload } = useAgentMessages(fallback, runId === patrolRuns[0].id ? fallbackLabel : `样例 · ${runId}`)
  const speaker = messages[messages.length - 1]?.agentKey

  return (
    <PageFrame title="对话" fill>
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-[#EEF0F3] px-5 py-3">
          {source === 'live' ? (
            <span className="flex items-center gap-2 text-sm text-dim">
              {runLabel}
              <span className="inline-flex h-6 items-center gap-1.5 rounded-btn bg-[#E8F5EC] px-2 text-xs leading-none text-[#1F7A45]">
                <span className="h-1.5 w-1.5 rounded-full bg-[#1F7A45]" aria-hidden="true" />
                实时消息
              </span>
            </span>
          ) : (
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
          )}
          <span className="inline-flex h-6 items-center rounded-btn bg-[#F2F3F5] px-2 text-xs leading-none text-mute">
            {source === 'live' ? '后端消息' : '本地样例'}
          </span>
          <button type="button" className="ml-auto text-sm text-tea" onClick={reload}>
            刷新
          </button>
        </div>
        <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_240px]">
          <div className="min-h-0 overflow-auto px-4 py-4 sm:px-5">
            {messages.length === 0 ? (
              <p className="grid h-full place-items-center text-sm text-mute">这次执行还没有 Agent 发言。</p>
            ) : (
              <div className="grid gap-4">
                {messages.map((message) => (
                  <Message key={message.id} message={message} />
                ))}
              </div>
            )}
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

function Message({ message }: { message: UiMessage }) {
  const agent = agents.find((item) => item.key === message.agentKey)
  const denied = message.calls?.some((call) => call.result.status === 'denied') ?? false
  return (
    <article className="flex items-start gap-3">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-ink text-lg" aria-hidden="true">
        {agent?.avatar ?? '🌿'}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-sm text-paper">{agent?.name ?? message.agentKey}</span>
          <time className="num text-xs text-mute">{message.at}</time>
        </div>
        <div className="mt-1 max-w-3xl overflow-hidden rounded-2xl bg-[#F7F8FA]">
          {message.degraded ? <p className="bg-[#FFF4CC] px-3 py-2 text-sm text-[#8A6414]">⚠️ 模型降级中（规则模板输出）</p> : null}
          <p className="px-3 py-2 text-sm leading-normal text-paper">
            <RichText text={message.content} citations={message.citations} />
          </p>
          {denied ? <p className="bg-[#F2F3F5] px-3 py-2 text-sm text-dim">⛔ 权限不足：send_device_cmd（已拦截）</p> : null}
        </div>
        {message.calls?.map((call) => (
          <ToolBlock key={call.name} call={call} />
        ))}
        {message.citations ? <CitationList citations={message.citations} /> : null}
      </div>
    </article>
  )
}

/** `[n]` 的编号由前端按返回顺序生成（1 开始、不跳号），不依赖后端给 id */
function RichText({ text, citations }: { text: string; citations?: Citation[] }) {
  const parts = useMemo(() => text.split(/(\[\d+\])/g), [text])
  return (
    <>
      {parts.map((part, index) => {
        const match = /^\[(\d+)\]$/.exec(part)
        if (!match) return <span key={index}>{part}</span>
        const cite = citations?.[Number(match[1]) - 1]
        return (
          <span key={index} className="group relative inline-block">
            <a href={`#cite-${match[1]}`} className="text-tea underline decoration-tea underline-offset-2">
              [{match[1]}]
            </a>
            {cite ? (
              <span className="pointer-events-none absolute left-0 top-full z-10 mt-1 hidden w-72 rounded-lg bg-paper px-2 py-2 text-xs leading-normal text-white shadow group-hover:block">
                <span className="num mb-1 block text-[11px] text-white/60">
                  {cite.title} · 第 {cite.chunk_index + 1} 块 · 相关度 {cite.score.toFixed(2)}
                </span>
                {cite.chunk_text}
              </span>
            ) : null}
          </span>
        )
      })}
    </>
  )
}

/**
 * 引用块（contract 第 8 节）：
 * - 标题直接用 `title`，不带路径；`chunk_text` 原样整段显示，不截断成一行；
 * - `score` 0-1 原样两位，不转百分比；
 * - 同一文档可能命中多块，按返回顺序全列，不按 doc_id 去重；
 * - 空数组 = 未检索到，显示空态，不是错误。
 */
function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) {
    return (
      <p className="mt-2 max-w-3xl rounded-lg border border-dashed border-line px-3 py-2 text-sm leading-normal text-mute">
        知识库中未检索到相关内容（这是正常结果，不是报错）
      </p>
    )
  }

  return (
    <ol className="mt-2 grid max-w-3xl gap-2">
      {citations.map((cite, index) => (
        <li key={`${cite.doc_id}-${cite.chunk_index}-${index}`} id={`cite-${index + 1}`} className="rounded-lg border border-line bg-panel px-3 py-2">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="num text-xs text-tea">[{index + 1}]</span>
            <span className="text-sm leading-normal text-paper">{cite.title}</span>
            <span className="num text-xs leading-none text-mute">第 {cite.chunk_index + 1} 块</span>
            <span className="num text-xs leading-none text-mute">相关度 {cite.score.toFixed(2)}</span>
          </div>
          <p className="mt-1 text-sm leading-normal text-dim">{cite.chunk_text}</p>
        </li>
      ))}
    </ol>
  )
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
