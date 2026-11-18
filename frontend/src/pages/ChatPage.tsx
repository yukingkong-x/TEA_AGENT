import { useMemo, useState } from 'react'
import { GlassCard } from '../components/GlassCard'
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
  const spoken = useMemo(() => new Set(messages.map((m) => m.agentKey)), [messages])

  return (
    <PageFrame title="对话" fill>
      <GlassCard className="flex h-full min-h-0 flex-col overflow-hidden" tilt={false}>
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
            <Segmented
              label="选择一次巡园"
              options={patrolRuns.map((run) => ({ value: run.id, label: run.name }))}
              value={runId}
              onChange={setRunId}
            />
          )}
          <span className="inline-flex h-6 items-center rounded-btn bg-[#F2F3F5] px-2 text-xs leading-none text-mute">
            {source === 'live' ? '后端消息' : '本地样例'}
          </span>
          <button type="button" className="ml-auto text-sm text-tea" onClick={reload}>
            刷新
          </button>
        </div>
        <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_264px]">
          <div className="min-h-0 overflow-auto px-4 py-4 sm:px-5">
            {messages.length === 0 ? (
              <TeamLineup />
            ) : (
              <div className="grid gap-4">
                {messages.map((message, index) => (
                  <Message
                    key={message.id}
                    message={message}
                    grouped={index > 0 && messages[index - 1].agentKey === message.agentKey}
                    latest={message.agentKey === speaker}
                  />
                ))}
              </div>
            )}
          </div>
          <aside className="min-h-0 overflow-auto border-t border-[#EEF0F3] p-4 lg:border-l lg:border-t-0">
            <h2 className="px-2 text-paper">本轮成员</h2>
            <p className="mt-1 px-2 text-xs leading-none text-mute">按工作流顺序接力发言</p>
            <ul className="mt-3 grid gap-1.5">
              {agents.map((agent) => {
                const speaking = agent.key === speaker
                const done = spoken.has(agent.key)
                return (
                  <li
                    key={agent.key}
                    className={`flex items-center gap-3 rounded-[14px] px-2 py-2 transition-colors duration-200 ${
                      speaking ? 'bg-panel2' : ''
                    }`}
                  >
                    <span
                      className={`relative grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-[12px] bg-white/80 ring-1 ${
                        speaking ? 'ring-tea' : 'ring-black/5'
                      } ${speaking ? 'avatar-live' : ''}`}
                      aria-hidden="true"
                    >
                      <img src={agent.img} alt="" className="h-full w-full object-cover" loading="lazy" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className={`block text-sm leading-normal ${speaking ? 'text-tea' : 'text-paper'}`}>{agent.name}</span>
                      <span className="block truncate text-xs leading-none text-mute">{agent.job}</span>
                    </span>
                    <span
                      className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                        speaking ? 'bg-tea' : done ? 'bg-[#9ED8B6]' : 'bg-[#D9DEE5]'
                      }`}
                      title={speaking ? '发言中' : done ? '已完成' : '待命'}
                      aria-label={speaking ? '发言中' : done ? '已完成' : '待命'}
                    />
                  </li>
                )
              })}
            </ul>
          </aside>
        </div>
      </GlassCard>
    </PageFrame>
  )
}

/* ------------------------------------------------------------ 头部：Apple 分段控件 */

function Segmented({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: string; label: string }[]
  value: string
  onChange: (value: string) => void
  label: string
}) {
  return (
    <div role="tablist" aria-label={label} className="flex shrink-0 rounded-full bg-[#E9EDEF] p-1">
      {options.map((option) => {
        const active = option.value === value
        return (
          <button
            key={option.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={`h-8 rounded-full px-3.5 text-sm leading-none transition-all duration-200 ${
              active
                ? 'bg-white text-paper shadow-[0_1px_3px_rgba(22,28,45,0.12)]'
                : 'text-dim hover:text-paper'
            }`}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------ 空态：七人合影 */

function TeamLineup() {
  return (
    <div className="grid h-full place-items-center">
      <div className="text-center">
        <div className="flex items-end justify-center gap-1.5">
          {agents.map((agent, index) => (
            <div key={agent.key} className="w-14 sm:w-16" style={{ transform: `translateY(${Math.abs(index - 3) * 3}px)` }}>
              <img src={agent.img} alt={agent.name} className="h-auto w-full drop-shadow-[0_6px_14px_rgba(23,48,38,0.16)]" loading="lazy" />
              <p className="mt-1 text-[11px] leading-none text-mute">{agent.name}</p>
            </div>
          ))}
        </div>
        <p className="mt-4 text-sm text-mute">这次执行还没有 Agent 发言。</p>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------ 消息气泡 */

function Message({ message, grouped, latest }: { message: UiMessage; grouped: boolean; latest: boolean }) {
  const agent = agents.find((item) => item.key === message.agentKey)
  const denied = message.calls?.some((call) => call.result.status === 'denied') ?? false
  return (
    <article className="flex items-end gap-2.5">
      {grouped ? (
        // 连续发言只出现一次立绘：占位保持对齐，名字与时间也并进上一条
        <span className="w-[88px] shrink-0" aria-hidden="true" />
      ) : (
        <span className="w-[88px] shrink-0 self-end">
          <img
            src={agent?.img}
            alt={agent?.name}
            className={`char h-[88px] w-[88px] object-contain object-bottom ${latest ? 'is-live' : ''}`}
          />
        </span>
      )}
      <div className="min-w-0 flex-1 pb-1">
        {!grouped ? (
          <div className="flex items-baseline gap-2">
            <span className="text-sm text-paper">{agent?.name ?? message.agentKey}</span>
            <time className="num text-xs text-mute">{message.at}</time>
          </div>
        ) : null}
        {/*
         * 毛玻璃气泡：白 55% + backdrop-blur + 白内高光，和整页玻璃卡同材质。
         * 组内第一条带左下尖角指向立绘（对话剧样式），后续条齐角。
         */}
        <div
          className={`mt-1 max-w-3xl overflow-hidden shadow-[0_1px_2px_rgba(22,28,45,0.05),inset_0_1px_0_rgba(255,255,255,0.85)] ring-1 ring-white/70 backdrop-blur-md transition-colors duration-300 ${
            grouped ? 'rounded-[16px]' : 'rounded-[16px] rounded-bl-[4px]'
          } ${latest ? 'bg-white/85 ring-tea/20' : 'bg-white/55'}`}
        >
          {message.degraded ? <p className="bg-[#FFF4CC] px-3.5 py-2 text-sm text-[#8A6414]">⚠️ 模型降级中（规则模板输出）</p> : null}
          <p className="px-3.5 py-2.5 text-sm leading-normal text-paper">
            <RichText text={message.content} citations={message.citations} />
          </p>
          {denied ? <p className="bg-[#F2F3F5]/90 px-3.5 py-2 text-sm text-dim">⛔ 权限不足：send_device_cmd（已拦截）</p> : null}
        </div>
        {message.calls?.length ? <ToolGroup calls={message.calls} /> : null}
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
 * - score 0-1 原样两位，不转百分比；
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

/**
 * 工具调用折叠成一个小胶囊：一条消息常常带 2-3 次调用，全部展开会把消息流撑得很长。
 * 默认只显示「N 次工具调用」，点开才逐条展开 args/result。
 */
function ToolGroup({ calls }: { calls: ToolCall[] }) {
  const [open, setOpen] = useState(false)
  const denied = calls.some((call) => call.result.status === 'denied')
  return (
    <div className="mt-1.5 max-w-3xl">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className={`inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-xs leading-none transition-colors ${
          denied ? 'bg-[#FDF0EC] text-[#B4572A]' : 'bg-[#EEF1F4] text-dim hover:bg-[#E5EAEE]'
        }`}
      >
        <span aria-hidden="true">🔧</span>
        {calls.length} 次工具调用{denied ? ' · 1 次被拦截' : ''}
        <span className={`transition-transform duration-200 ${open ? 'rotate-180' : ''}`} aria-hidden="true">
          ⌄
        </span>
      </button>
      {open ? (
        <div className="mt-2 grid gap-2">
          {calls.map((call, index) => (
            // key 用「工具名+序号」：Self-Loop 两轮都会调 verify_result / send_device_cmd，
            // 只用工具名会撞 key（React 控制台 warning，且第二块的展开状态会被沿用）
            <div key={`${call.name}-${index}`} className="overflow-hidden rounded-lg bg-[#F7F8FA]/90">
              <p className="num border-b border-[#EEF0F3]/80 px-3 py-1.5 text-xs text-tea">{call.name}</p>
              <pre className="num overflow-auto p-3 text-xs leading-normal text-dim">
                {JSON.stringify({ args: call.args, result: call.result }, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}
