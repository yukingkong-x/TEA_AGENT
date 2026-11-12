import { type ReactNode } from 'react'
import { Handle, NodeToolbar, Position, type NodeProps } from '@xyflow/react'
import { agents } from '../data/snapshot'
import type { FlowData, FlowNode, RunStatus } from '../data/workflow'

const statusText: Record<RunStatus, string> = {
  idle: '待命',
  running: '执行中',
  done: '完成',
  failed: '失败',
}

const port = '!h-2.5 !w-2.5 !border-2 !border-white !bg-tea'

function shell(status: RunStatus, selected: boolean) {
  const tone =
    status === 'running'
      ? 'border-tea breath'
      : status === 'done'
        ? 'border-tea'
        : status === 'failed'
          ? 'border-danger'
          : 'border-line'
  return `border bg-panel text-left shadow-none ${tone} ${selected ? 'ring-2 ring-tea' : ''}`
}

function RunBadge({ status }: { status: RunStatus }) {
  const tone =
    status === 'failed'
      ? 'bg-[#FFECE8] text-danger'
      : status === 'running' || status === 'done'
        ? 'bg-panel2 text-tea'
        : 'bg-[#F2F3F5] text-mute'
  return <span className={`inline-flex h-5 shrink-0 items-center rounded-btn px-1.5 text-xs leading-none ${tone}`}>{statusText[status]}</span>
}

function Check() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4 shrink-0 text-tea" aria-hidden="true">
      <path d="M3 8.2 6.2 11.4 13 4.6" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  )
}

function SpeechPop({ data }: { data: FlowData }) {
  if (!data.speech && !data.calls?.length) return null
  return (
    <NodeToolbar position={Position.Right} offset={12} className="max-w-[260px] rounded-card border border-line bg-panel px-3 py-2 text-left">
      <p className="text-sm leading-normal text-paper">{data.speech}</p>
      {data.calls?.map((call) => (
        <p key={call.name} className="mt-1 text-xs leading-normal text-mute">
          {call.name} · {call.detail}
        </p>
      ))}
    </NodeToolbar>
  )
}

function Mark({ children }: { children: ReactNode }) {
  return <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-ink text-tea">{children}</span>
}

export function AgentNode({ data, selected }: NodeProps<FlowNode>) {
  const agent = agents.find((item) => item.key === data.agentKey)
  return (
    <div className={`w-[240px] rounded-card px-3 py-2.5 ${shell(data.status, selected)}`}>
      <SpeechPop data={data} />
      <Handle type="target" position={Position.Top} className={port} />
      <Handle type="source" position={Position.Bottom} className={port} />
      {data.loopOut ? (
        <>
          <Handle type="source" id="loop" position={Position.Right} style={{ top: '32%' }} className={port} />
          <Handle type="target" id="again" position={Position.Right} style={{ top: '72%' }} className={port} />
        </>
      ) : null}
      <div className="flex items-center gap-2.5">
        <Mark>
          <span className="text-base" aria-hidden="true">
            {agent?.avatar ?? '·'}
          </span>
        </Mark>
        <span className="min-w-0 flex-1">
          <span className="flex items-center justify-between gap-2">
            <span className="truncate text-sm font-normal leading-normal text-paper">{data.name}</span>
            {data.status === 'done' ? <Check /> : data.status === 'idle' ? null : <RunBadge status={data.status} />}
          </span>
          <span className="mt-0.5 block truncate text-xs leading-none text-mute">{agent?.name ?? '智能体'}</span>
        </span>
      </div>
    </div>
  )
}

export function TermNode({ data, selected }: NodeProps<FlowNode>) {
  const start = data.kind === 'start'
  return (
    <div className={`rounded-full px-4 py-1.5 text-sm ${shell(data.status, selected)}`}>
      {start ? null : <Handle type="target" position={Position.Top} className={port} />}
      {start ? <Handle type="source" position={Position.Bottom} className={port} /> : null}
      <span className="text-paper">{data.name}</span>
    </div>
  )
}

export function ParallelNode({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div className={`w-[240px] rounded-card px-3 py-2.5 ${shell(data.status, selected)}`}>
      <Handle type="target" position={Position.Top} className={port} />
      <Handle type="source" position={Position.Bottom} className={port} />
      <div className="flex items-center gap-2.5">
        <Mark>
          <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true">
            <path d="M8 2 v4 M8 6 H3 v6 M8 6 H13 v6" fill="none" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </Mark>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-normal leading-normal text-paper">{data.name}</span>
          <span className="mt-0.5 block text-xs leading-none text-mute">并行 · 三路同时出发</span>
        </span>
      </div>
    </div>
  )
}

export function ConditionNode({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div className={`w-[240px] rounded-card px-3 py-2.5 ${shell(data.status, selected)}`}>
      <SpeechPop data={data} />
      <Handle type="target" position={Position.Top} className={port} />
      <Handle type="source" id="yes" position={Position.Bottom} style={{ left: '28%' }} className={port} />
      <Handle type="source" id="no" position={Position.Bottom} style={{ left: '72%' }} className={port} />
      <div className="flex items-center gap-2.5">
        <Mark>
          <span className="h-3.5 w-3.5 rotate-45 border-2 border-tea" aria-hidden="true" />
        </Mark>
        <span className="min-w-0 flex-1">
          <span className="flex items-center justify-between gap-2">
            <span className="truncate text-sm font-normal leading-normal text-paper">{data.name}</span>
            {data.status === 'idle' ? null : <RunBadge status={data.status} />}
          </span>
          <span className="mt-0.5 block text-xs leading-none text-mute">左浇水 · 右不浇</span>
        </span>
      </div>
    </div>
  )
}

export function ToolNode({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div className={`w-[240px] rounded-card px-3 py-2.5 ${shell(data.status, selected)}`}>
      <SpeechPop data={data} />
      <Handle type="target" position={Position.Top} className={port} />
      <Handle type="source" position={Position.Bottom} className={port} />
      <div className="flex items-center gap-2.5">
        <Mark>
          <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true">
            <circle cx="8" cy="8" r="5.2" fill="none" stroke="currentColor" strokeWidth="1.6" />
            <path d="M8 5.2 V8 l2 1.4" fill="none" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </Mark>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-normal leading-normal text-paper">{data.name}</span>
          {data.status === 'running' && typeof data.remain === 'number' ? (
            <span className="num mt-0.5 block text-xs leading-none text-tea">剩余 {data.remain} 秒</span>
          ) : (
            <span className="mt-0.5 block text-xs leading-none text-mute">工具 · 等到点再往下</span>
          )}
        </span>
      </div>
    </div>
  )
}

export function LoopNode({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div className={`w-[240px] rounded-card border-dashed px-3 py-2.5 ${shell(data.status, selected)}`}>
      <SpeechPop data={data} />
      <Handle type="target" position={Position.Left} style={{ top: '32%' }} className={port} />
      <Handle type="source" id="back" position={Position.Left} style={{ top: '72%' }} className={port} />
      <div className="flex items-center gap-2.5">
        <Mark>
          <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true">
            <path d="M11 3.5 A4.5 4.5 0 1 0 12.2 8" fill="none" stroke="currentColor" strokeWidth="1.6" />
            <path d="M12.2 5.2 V8 H9.4" fill="none" stroke="currentColor" strokeWidth="1.6" />
          </svg>
        </Mark>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-normal leading-normal text-paper">{data.name}</span>
          <span className="mt-0.5 block text-xs leading-none text-mute">循环 · 最多 {data.maxIterations ?? 2} 轮</span>
        </span>
      </div>
    </div>
  )
}

export const nodeTypes = {
  start: TermNode,
  end: TermNode,
  agent: AgentNode,
  parallel: ParallelNode,
  condition: ConditionNode,
  tool: ToolNode,
  loop: LoopNode,
}
