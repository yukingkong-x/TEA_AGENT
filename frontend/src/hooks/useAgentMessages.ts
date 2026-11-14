/**
 * 对话剧场数据源。
 *
 * 之前 agent_messages 表是空的，剧场只能吃本地假数据；现在 agent 节点产出会落库 + 推 WS，
 * 所以优先读 `GET /api/runs/{id}`（含 messages），并用 `agent_message` 事件续播，
 * 拉不到时（后端没起 / 没跑过 workflow）回退 `src/data/chat.ts` 的样例，页面不空。
 *
 * 两条渲染口径（contract 第 5、8 节）：
 * - 文本以「⚠️ 模型降级中」开头 → 顶部降级徽章，该行之后才是正文；
 * - citations 空数组 = 未检索到，是正常结果，不是错误。
 */
import { useEffect, useState } from 'react'
import { endpoints } from '../api/endpoints'
import { dashboardSocket } from '../api/socket'
import type { AgentMessageDto, KnowledgeHitDto } from '../api/types'
import { formatClock } from '../lib/parseTs'

const DEGRADE_MARK = '⚠️ 模型降级中'

export type UiCall = { name: string; args: Record<string, unknown>; result: Record<string, unknown> }

export type UiMessage = {
  id: string
  at: string
  agentKey: string
  content: string
  degraded?: boolean
  calls?: UiCall[]
  /** undefined = 本条没有检索动作；[] = 检索了但没命中 */
  citations?: KnowledgeHitDto[]
}

function splitDegraded(raw: string): { content: string; degraded: boolean } {
  if (!raw.startsWith(DEGRADE_MARK)) return { content: raw, degraded: false }
  return { content: raw.slice(DEGRADE_MARK.length).replace(/^\s*\n/, ''), degraded: true }
}

function toCalls(raw: unknown): UiCall[] | undefined {
  if (!Array.isArray(raw) || raw.length === 0) return undefined
  return raw.map((item, index) => {
    const record = (item ?? {}) as Record<string, unknown>
    return {
      name: String(record.name ?? record.tool ?? `call_${index}`),
      args: (record.arguments ?? record.args ?? {}) as Record<string, unknown>,
      result: (record.result ?? {}) as Record<string, unknown>,
    }
  })
}

function toCitations(raw: unknown): KnowledgeHitDto[] | undefined {
  if (!Array.isArray(raw)) return undefined
  return raw.map((item) => {
    const hit = (item ?? {}) as Record<string, unknown>
    return {
      title: String(hit.title ?? '未命名文档'),
      chunk_text: String(hit.chunk_text ?? ''),
      score: typeof hit.score === 'number' ? hit.score : 0,
      doc_id: typeof hit.doc_id === 'number' ? hit.doc_id : 0,
      chunk_index: typeof hit.chunk_index === 'number' ? hit.chunk_index : 0,
    }
  })
}

function fromDto(dto: AgentMessageDto): UiMessage {
  const { content, degraded } = splitDegraded(dto.content ?? '')
  return {
    id: String(dto.id),
    at: formatClock(dto.created_at),
    agentKey: dto.agent_key,
    content,
    degraded,
    calls: toCalls(dto.tool_calls),
    citations: toCitations(dto.citations),
  }
}

export type AgentMessages = {
  messages: UiMessage[]
  source: 'live' | 'mock'
  runLabel: string
  runId: number | null
  reload: () => void
}

export function useAgentMessages(fallback: UiMessage[], fallbackLabel: string): AgentMessages {
  const [messages, setMessages] = useState<UiMessage[]>(fallback)
  const [source, setSource] = useState<'live' | 'mock'>('mock')
  const [runId, setRunId] = useState<number | null>(null)
  const [runLabel, setRunLabel] = useState(fallbackLabel)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let alive = true
    async function load() {
      try {
        const runs = await endpoints.runs(1, 5)
        const latest = runs.items?.[0]
        if (!latest) throw new Error('还没有执行实例')
        const detail = await endpoints.run(latest.id)
        if (!alive) return
        const list = (detail.messages ?? []).map(fromDto)
        if (list.length === 0) throw new Error('这次执行还没有消息')
        setRunId(latest.id)
        setRunLabel(`运行 #${latest.id} · ${latest.trigger ?? 'manual'}`)
        setMessages(list)
        setSource('live')
      } catch {
        if (!alive) return
        setMessages(fallback)
        setRunLabel(fallbackLabel)
        setSource('mock')
      }
    }
    void load()
    return () => {
      alive = false
    }
  }, [fallback, fallbackLabel, nonce])

  // 实时续播：agent 节点产出即推 agent_message
  useEffect(() => {
    const off = dashboardSocket.on<AgentMessageDto>('agent_message', (data) => {
      if (!data?.agent_key) return
      if (runId !== null && typeof data.run_id === 'number' && data.run_id !== runId) return
      const message = fromDto(data)
      setMessages((current) => (current.some((item) => item.id === message.id) ? current : current.concat(message)))
      setSource('live')
    })
    return off
  }, [runId])

  return { messages, source, runLabel, runId, reload: () => setNonce((value) => value + 1) }
}
