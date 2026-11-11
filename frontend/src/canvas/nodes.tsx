import { Handle, Position, type NodeProps } from '@xyflow/react'
import { agents } from '../data/snapshot'
import type { FlowNode, RunStatus } from '../data/workflow'

const statusText: Record<RunStatus, string> = {
  idle: '待命',
  running: '执行中',
  done: '完成',
  failed: '失败',
}

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

function Handles({ loop }: { loop?: boolean }) {
  return (
    <>
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-tea" />
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !border-0 !bg-tea" />
      {loop ? (
        <Handle type="source" id="loop" position={Position.Bottom} className="!h-2 !w-2 !border-0 !bg-tea" />
      ) : null}
    </>
  )
}

function Check() {
  return (
    <svg viewBox="0 0 16 16" className="h-4 w-4 text-tea" aria-hidden="true">
      <path d="M3 8.2 6.2 11.4 13 4.6" fill="none" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  )
}

export function AgentNode({ data, selected }: NodeProps<FlowNode>) {
  const agent = agents.find((item) => item.key === data.agentKey)
  return (
    <div className={`flex w-[176px] items-center gap-2 rounded-card px-3 py-2 ${shell(data.status, selected)}`}>
      <Handles loop={data.loopOut} />
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-ink text-sm text-tea">{agent?.mark ?? '体'}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm text-paper">{data.name}</span>
        <span className="block text-[12px] text-dim">{statusText[data.status]}</span>
      </span>
      {data.status === 'done' ? <Check /> : null}
    </div>
  )
}

export function TermNode({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div className={`rounded-full px-4 py-2 text-sm ${shell(data.status, selected)}`}>
      <Handles />
      <span className="text-paper">{data.name}</span>
    </div>
  )
}

export function ParallelNode({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div className={`w-[156px] rounded-btn px-3 py-2 ${shell(data.status, selected)}`}>
      <Handles />
      <span className="block text-[12px] text-dim">并行</span>
      <span className="block text-sm text-paper">{data.name}</span>
    </div>
  )
}

export function ConditionNode({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div className={`relative grid h-[104px] w-[104px] place-items-center ${selected ? 'ring-2 ring-tea rounded-btn' : ''}`}>
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !border-0 !bg-tea" />
      <Handle type="source" id="yes" position={Position.Right} style={{ top: 32 }} className="!h-2 !w-2 !border-0 !bg-tea" />
      <Handle type="source" id="no" position={Position.Right} style={{ top: 72 }} className="!h-2 !w-2 !border-0 !bg-tea" />
      <span
        className={`h-16 w-16 rotate-45 border bg-panel ${
          data.status === 'running' ? 'border-tea breath' : data.status === 'done' ? 'border-tea' : 'border-line'
        }`}
      />
      <span className="absolute text-center text-[12px] leading-tight text-paper">
        {data.name}
        <span className="mt-0.5 block text-[11px] text-dim">{statusText[data.status]}</span>
      </span>
    </div>
  )
}

export function ToolNode({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div className={`w-[168px] rounded-card px-3 py-2 ${shell(data.status, selected)}`}>
      <Handles />
      <span className="block text-[12px] text-dim">工具</span>
      <span className="block text-sm text-paper">{data.name}</span>
      {data.status === 'running' && typeof data.remain === 'number' ? (
        <span className="num mt-1 block text-sm text-tea">剩余 {data.remain} 秒</span>
      ) : (
        <span className="block text-[12px] text-dim">{statusText[data.status]}</span>
      )}
    </div>
  )
}

export function LoopNode({ data, selected }: NodeProps<FlowNode>) {
  return (
    <div className={`w-[168px] rounded-card border-dashed px-3 py-2 ${shell(data.status, selected)}`}>
      <Handles />
      <span className="block text-[12px] text-dim">循环 · 最多 {data.maxIterations ?? 2} 轮</span>
      <span className="block text-sm text-paper">{data.name}</span>
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
