/**
 * 画布右侧「运行对话」抽屉。
 *
 * 目的是录屏时一屏同看「结构 + 内容」：左边画布节点逐个点亮，
 * 右边同一条 run 的智能体发言实时滚出来，不用切页面、不用后期画中画。
 *
 * 数据口径与对话页完全一致：
 * - 打开时按 runId 拉 `GET /api/runs/{id}` 的 messages；runId 还没产生就退到「最近一次运行」
 * - 运行中靠 WS `agent_message` 续播，按 run_id 过滤，别的 run 的消息不会串进来
 * - 只读，不改任何状态；找不到后端就如实显示空态，不塞样例发言
 *
 * 排版原则（这里是给人读的稿子，不是日志）：
 * - 去掉 `-` `*` 这类列表符号，需要列举时用留白与细引线表达层级
 * - 数字区间用连接号「–」，不再出现 ASCII 连字符；任务 ID 里的连字符保留，但做成等宽小标签
 * - `<离线>` 这种尖括号改成「离线」，避免看起来像 HTML 标签
 * - 段首【巡园播报】抽成小徽章，正文另起，避免一行里堆满括号
 */
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { endpoints } from '../api/endpoints'
import { dashboardSocket } from '../api/socket'
import type { AgentMessageDto } from '../api/types'
import type { UiMessage } from '../hooks/useAgentMessages'
import { fromDto } from '../hooks/useAgentMessages'
import { agents } from '../data/snapshot'

const EXPAND_AT = 160

/* 宽度：默认 480，左边缘可拖，范围 360–760，记在本地 */
const WIDTH_KEY = 'zhiqiu.canvas.drawerWidth'
const MIN_WIDTH = 360
const MAX_WIDTH = 760

function readWidth(): number {
  try {
    const saved = Number(window.localStorage.getItem(WIDTH_KEY))
    if (Number.isFinite(saved) && saved >= MIN_WIDTH && saved <= MAX_WIDTH) return saved
  } catch {
    /* 隐私模式读不到就用默认值 */
  }
  return 480
}

/* ------------------------------------------------------------ 文稿清洗 */

/** 列表符号：连字符、星号、圆点、间隔号、破折号、加号 */
const BULLET = /^\s*[-*•·–—+]\s+/
const NUMBERED = /^\s*(\d{1,2})[.)、]\s+/

function tidy(line: string): string {
  return line
    .replace(/\u00a0/g, ' ')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\s+([，。；：、！？）》」】%）])/g, '$1')
    .replace(/([（《「【])\s+/g, '$1')
    .replace(/。{2,}/g, '。')
    .replace(/，{2,}/g, '，')
    /* 只把「短数字 - 短数字」当区间连接号替换（兼容 55%-65%），避免把 task-20261118-0003 打散 */
    .replace(/(?<!\d)(\d{1,3}%?)\s*[-~～]\s*(\d{1,3}%?)(?!\d)/g, '$1–$2')
    /* <离线> → 「离线」：尖括号在正文里像 HTML 标签 */
    .replace(/<([^<>\n]{1,24})>/g, '「$1」')
    /* 单独用作分隔的连字符改成逗号 */
    .replace(/\s+-\s+/g, '，')
    .replace(/\s+/g, ' ')
    .trim()
}

type Block = { kind: 'para' | 'item' | 'num'; text: string; order?: string }

function parseSpeech(raw: string): Block[] {
  const lines = raw.replace(/\r\n/g, '\n').split('\n')
  const blocks: Block[] = []
  for (const line of lines) {
    const text = tidy(line)
    if (!text) continue
    const numbered = text.match(NUMBERED)
    if (BULLET.test(text)) {
      blocks.push({ kind: 'item', text: text.replace(BULLET, '') })
    } else if (numbered) {
      blocks.push({ kind: 'num', text: text.replace(NUMBERED, ''), order: numbered[1] })
    } else {
      blocks.push({ kind: 'para', text })
    }
  }
  return blocks
}

/** 行内强调：**粗体** 走中黑；任务 ID 走等宽小标签，避免一串连字符糊在正文里 */
const INLINE_TOKEN = /(\*\*[^*]+\*\*|\b[a-zA-Z]{2,}-\d{6,}-\d{3,}\b)/g

function inline(text: string): ReactNode[] {
  return text
    .split(INLINE_TOKEN)
    .filter(Boolean)
    .map((part, index) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return (
          <strong key={index} className="font-medium text-paper">
            {part.slice(2, -2)}
          </strong>
        )
      }
      if (/^[a-zA-Z]{2,}-\d{6,}-\d{3,}$/.test(part)) {
        return (
          <span
            key={index}
            className="num whitespace-nowrap rounded-[5px] bg-[#F1F3F0] px-1 py-[1px] text-[11.5px] leading-normal text-dim"
          >
            {part}
          </span>
        )
      }
      return <span key={index}>{part}</span>
    })
}

/** 段首【巡园播报】抽成徽章，正文单独排版 */
function Paragraph({ text }: { text: string }) {
  const head = text.match(/^【([^】]{1,10})】\s*(.*)$/)
  if (head) {
    return (
      <p>
        <span className="mr-1.5 inline-flex translate-y-[-1px] items-center rounded-[5px] bg-[#EAF5EE] px-1.5 py-[1px] text-[11px] leading-normal text-[#1F7A45]">
          {head[1]}
        </span>
        {inline(head[2])}
      </p>
    )
  }
  return <p>{inline(text)}</p>
}

function SpeechText({ text }: { text: string }) {
  const blocks = parseSpeech(text)
  return (
    <div className="mt-1.5 space-y-[7px] text-[13px] leading-[1.75] text-paper">
      {blocks.map((block, index) =>
        block.kind === 'item' ? (
          <p key={index} className="border-l-2 border-[#E2EDE5] pl-2.5">
            {inline(block.text)}
          </p>
        ) : block.kind === 'num' ? (
          <p key={index} className="flex gap-1.5">
            <span className="num mt-[3px] shrink-0 text-[11px] leading-[1.6] text-mute">{block.order}</span>
            <span className="min-w-0">{inline(block.text)}</span>
          </p>
        ) : (
          <Paragraph key={index} text={block.text} />
        ),
      )}
    </div>
  )
}

/* ------------------------------------------------------------ 抽屉本体 */

export function RunChatDrawer({
  open,
  runId,
  running,
  onClose,
}: {
  open: boolean
  runId: number | null
  running: boolean
  onClose: () => void
}) {
  const [messages, setMessages] = useState<UiMessage[]>([])
  const [label, setLabel] = useState('等待运行…')
  const [live, setLive] = useState(false)
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const listRef = useRef<HTMLDivElement | null>(null)
  const stick = useRef(true)
  const [width, setWidth] = useState(readWidth)
  const [resizing, setResizing] = useState(false)
  const widthRef = useRef(width)
  widthRef.current = width

  /* 左边缘拖拽改宽：向右拖变窄、向左拖变宽，松手落本地 */
  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = widthRef.current
    /* 松手时 React 可能还没重渲染，widthRef 会是旧值，所以自己记一份最新宽度 */
    let latest = startWidth
    setResizing(true)
    const previousSelect = document.body.style.userSelect
    document.body.style.userSelect = 'none'
    const onMove = (moveEvent: PointerEvent) => {
      latest = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + (startX - moveEvent.clientX)))
      setWidth(latest)
    }
    const onUp = () => {
      setResizing(false)
      document.body.style.userSelect = previousSelect
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      try {
        window.localStorage.setItem(WIDTH_KEY, String(latest))
      } catch {
        /* 存不下就只影响下次默认宽度 */
      }
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  /* 打开或换 run 时补历史：中途才展开抽屉也能看到前面已经说过的话 */
  useEffect(() => {
    if (!open) return
    let alive = true
    setLoading(true)
    async function load() {
      try {
        let id = runId
        if (id === null) {
          const page = await endpoints.runs(1, 1)
          id = page.items?.[0]?.id ?? null
        }
        if (!id) {
          if (alive) {
            setMessages([])
            setLabel('还没有执行记录')
          }
          return
        }
        const detail = await endpoints.run(id)
        if (!alive) return
        setMessages((detail.messages ?? []).map(fromDto))
        setLabel(runId === null ? `最近一次运行 #${id}` : `运行 #${id}`)
        setLive(true)
      } catch {
        if (!alive) return
        setMessages([])
        setLabel('后端未连通')
        setLive(false)
      } finally {
        if (alive) setLoading(false)
      }
    }
    void load()
    return () => {
      alive = false
    }
  }, [open, runId])

  /* 实时续播：只收本次 run 的消息，别的历史 run 不串台 */
  useEffect(() => {
    if (!open) return
    const off = dashboardSocket.on<AgentMessageDto>('agent_message', (data) => {
      if (!data?.agent_key) return
      if (runId !== null && typeof data.run_id === 'number' && data.run_id !== runId) return
      const message = fromDto(data)
      setMessages((current) => (current.some((item) => item.id === message.id) ? current : current.concat(message)))
      if (typeof data.run_id === 'number') setLabel(`运行 #${data.run_id}`)
      setLive(true)
    })
    return off
  }, [open, runId])

  /* 贴底跟随：用户往上翻历史时不再强行拽回底部 */
  useEffect(() => {
    if (!open) return
    const el = listRef.current
    if (!el || !stick.current) return
    el.scrollTop = el.scrollHeight
  }, [messages.length, open])

  if (!open) return null

  const speakers = new Set(messages.map((item) => item.agentKey)).size

  return (
    <aside
      aria-label="运行对话"
      style={{ width: `min(${width}px, 100%)` }}
      className="absolute inset-y-0 right-0 z-30 flex flex-col border-l border-line bg-white/85 backdrop-blur-xl lg:static lg:z-auto lg:shrink-0"
    >
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="拖动调整运行对话宽度"
        onPointerDown={startResize}
        className="absolute inset-y-0 -left-1 hidden w-2 cursor-col-resize lg:block"
      >
        <span
          className={`mx-auto block h-full w-[3px] rounded-full transition-colors ${
            resizing ? 'bg-tea/70' : 'bg-transparent hover:bg-tea/30'
          }`}
        />
      </div>
      <header className="shrink-0 border-b border-line px-4 py-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-paper">
              运行对话
              {running ? (
                <span className="inline-flex items-center gap-1 rounded-btn bg-[#E8F5EC] px-1.5 py-0.5 text-[11px] leading-none text-[#1F7A45]">
                  <span className="h-1.5 w-1.5 rounded-full bg-[#1F7A45] animate-pulse" aria-hidden="true" />
                  执行中
                </span>
              ) : null}
            </h2>
            <p className="num mt-1 truncate text-xs leading-none text-mute" title={label}>
              {label}
            </p>
            {messages.length ? (
              <p className="mt-1.5 flex gap-1.5 text-[11px] leading-none text-mute">
                <span className="rounded-[5px] bg-[#F2F4F1] px-1.5 py-0.5">{messages.length} 条发言</span>
                <span className="rounded-[5px] bg-[#F2F4F1] px-1.5 py-0.5">{speakers} 位智能体</span>
              </p>
            ) : null}
          </div>
          <button
            type="button"
            aria-label="收起运行对话"
            className="grid h-9 w-9 shrink-0 place-items-center rounded-btn text-mute hover:bg-panel2 hover:text-paper"
            onClick={onClose}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none" />
            </svg>
          </button>
        </div>
      </header>

      <div
        ref={listRef}
        onScroll={() => {
          const el = listRef.current
          if (!el) return
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
        }}
        className="min-h-0 flex-1 overflow-y-auto px-3 py-2"
      >
        {loading ? (
          <p className="px-1 py-6 text-center text-xs text-mute">正在读取这次运行的对话…</p>
        ) : messages.length === 0 ? (
          <div className="px-2 py-8 text-center">
            <div className="flex items-end justify-center gap-1 opacity-40">
              {agents.slice(0, 5).map((agent) => (
                <img key={agent.key} src={agent.img} alt="" className="h-10 w-auto object-contain" loading="lazy" />
              ))}
            </div>
            <p className="mt-3 text-xs leading-normal text-mute">
              {live ? '这次运行还没有智能体发言。' : label}
              <br />
              点左下「运行」后，七位智能体的发言会实时出现在这里。
            </p>
          </div>
        ) : (
          <ol className="grid gap-1">
            {messages.map((message) => {
              const agent = agents.find((item) => item.key === message.agentKey)
              const long = message.content.length > EXPAND_AT
              const isOpen = expanded[message.id]
              const callNames = message.calls?.map((call) => call.name).slice(0, 2).join('、')
              const denied = message.calls?.some((call) => call.result?.status === 'denied') ?? false
              return (
                <li key={message.id} className="rounded-[10px] px-2 py-2 transition-colors hover:bg-white/70">
                  <div className="flex gap-2.5">
                    <img
                      src={agent?.img}
                      alt={agent?.name ?? message.agentKey}
                      className="mt-0.5 h-7 w-7 shrink-0 object-contain object-bottom"
                      loading="lazy"
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-2">
                        <span className="truncate text-[13px] leading-none text-paper">
                          {agent?.name ?? message.agentKey}
                        </span>
                        <time className="num shrink-0 text-[11px] leading-none text-mute">{message.at.slice(-8)}</time>
                      </div>
                      <div className={long && !isOpen ? 'line-clamp-[12]' : ''}>
                        <SpeechText text={message.content} />
                      </div>
                      {long ? (
                        <button
                          type="button"
                          className="mt-1 text-[11px] leading-none text-tea"
                          onClick={() => setExpanded((current) => ({ ...current, [message.id]: !isOpen }))}
                        >
                          {isOpen ? '收起' : '展开全文'}
                        </button>
                      ) : null}
                      {message.degraded ? (
                        <p className="mt-1.5 rounded-btn bg-[#FFF4CC] px-2 py-1 text-[11px] leading-normal text-[#8A6414]">
                          模型降级中，本条为规则模板输出
                        </p>
                      ) : null}
                      {message.calls?.length ? (
                        <p className={`mt-1.5 text-[11px] leading-normal ${denied ? 'text-[#C0392B]' : 'text-mute'}`}>
                          工具调用 {message.calls.length} 次
                          {denied ? '，含权限拦截' : ''}
                          {callNames ? `：${callNames}${message.calls.length > 2 ? ' 等' : ''}` : ''}
                        </p>
                      ) : null}
                      {message.citations?.length ? (
                        <p
                          className="mt-1 truncate text-[11px] leading-normal text-mute"
                          title={message.citations[0]?.title}
                        >
                          引用 {message.citations.length} 条：{message.citations[0]?.title}
                        </p>
                      ) : null}
                    </div>
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </div>

      <footer className="shrink-0 border-t border-line px-4 py-2">
        <p className="text-[11px] leading-normal text-mute">内容取自运行记录与实时推送，只读展示；拖动左边缘可调宽</p>
      </footer>
    </aside>
  )
}
