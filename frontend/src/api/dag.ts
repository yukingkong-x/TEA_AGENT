/**
 * 画布 ⇄ 后端 dag_json 双向转换器。
 *
 * 两边是两种世界观，谁也没法直接吃对方的数据：
 *   React Flow：`nodes[] + edges[]`，连线是独立对象，字段驼峰（agentKey）。
 *   后端 dag_json：节点自己持有出边引用 `next / branches / body_next`，
 *                  `edges` 恒为 `[]`，坐标存节点 `position`，字段蛇形（agent_key）。
 *
 * 映射表（与 `backend/app/workflow/dag.py`、PRD 9.1 对齐）：
 *   agent      next   ← 唯一出边
 *   tool       next   ← 唯一出边
 *   start      next   ← 唯一出边
 *   end        无出边
 *   condition  branches: {"true": [...], "false": [...]}   ← sourceHandle yes / no
 *   parallel   branches: [b1, b2, ...]（数组，每路第一个节点）← 全部出边，按 y 排序
 *   loop       body_next ← sourceHandle 'back' 的边；next ← 其余出边
 *              exit_expression ← 节点的 expression（前端叫 expression，后端叫 exit_expression）
 */

import type { Edge, Node } from '@xyflow/react'
import type { DagJson, DagNode } from './types'
import type { FlowData } from '../data/workflow'

type FlowNode = Node<FlowData>

const COND_TRUE = 'yes'
const COND_FALSE = 'no'
const LOOP_BACK = 'back'

const outgoing = (edges: Edge[], id: string): Edge[] => edges.filter((edge) => edge.source === id)

function byPosition(nodes: FlowNode[], ids: string[]): string[] {
  const order = new Map(nodes.map((node, index) => [node.id, index]))
  return [...ids].sort((a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0))
}

/** 前端画布 → 后端 dag_json */
export function toDagJson(
  nodes: FlowNode[],
  edges: Edge[],
  meta: { wf_key?: string; name?: string } = {},
): DagJson {
  const dagNodes: DagNode[] = nodes.map((flowNode) => {
    const data = flowNode.data
    const kind = data.kind ?? (flowNode.type as FlowData['kind']) ?? 'agent'
    const outs = outgoing(edges, flowNode.id)

    const base: DagNode = {
      id: flowNode.id,
      type: kind,
      name: data.name,
      position: { x: Math.round(flowNode.position.x), y: Math.round(flowNode.position.y) },
    }

    if (kind === 'agent') {
      base.agent_key = data.agentKey
      base.input = data.input
    }
    if (kind === 'tool') {
      base.tool = data.tool
      base.params = data.params
      base.input = data.input
    }
    if (kind === 'condition') {
      base.expression = data.expression
      base.branches = {
        true: outs.filter((e) => e.sourceHandle === COND_TRUE).map((e) => e.target),
        false: outs.filter((e) => e.sourceHandle === COND_FALSE).map((e) => e.target),
      }
    }
    if (kind === 'parallel') {
      base.branches = byPosition(
        nodes,
        outs.map((e) => e.target),
      )
    }
    if (kind === 'loop') {
      const back = outs.find((e) => e.sourceHandle === LOOP_BACK)
      const forward = outs.filter((e) => e.sourceHandle !== LOOP_BACK)
      base.body_next = back?.target ?? null
      base.exit_expression = data.expression
      base.max_iterations = data.maxIterations ?? 1
      base.next = forward.length ? byPosition(nodes, forward.map((e) => e.target))[0] : null
    }
    if (['start', 'agent', 'tool', 'parallel'].includes(kind)) {
      base.next = outs.length ? byPosition(nodes, outs.map((e) => e.target))[0] : null
    }

    return base
  })

  return { wf_key: meta.wf_key, name: meta.name, nodes: dagNodes, edges: [] }
}

/** 后端 dag_json → 前端画布（用于「从后端回显」和「运行前对齐」） */
export function fromDagJson(dag: DagJson): { nodes: FlowNode[]; edges: Edge[] } {
  const nodes: FlowNode[] = []
  const edges: Edge[] = []
  const pushEdge = (source: string, target: string, sourceHandle?: string) => {
    if (!target) return
    edges.push({
      id: `${source}->${target}${sourceHandle ? `:${sourceHandle}` : ''}`,
      source,
      target,
      type: 'flow',
      sourceHandle,
      data: { active: false },
    } as Edge)
  }

  for (const [index, dagNode] of (dag.nodes ?? []).entries()) {
    const kind = (dagNode.type ?? 'agent') as FlowData['kind']
    nodes.push({
      id: dagNode.id,
      type: kind,
      position: dagNode.position ?? { x: 0, y: index * 160 },
      data: {
        name: dagNode.name ?? dagNode.id,
        kind,
        agentKey: dagNode.agent_key,
        input: dagNode.input,
        expression: kind === 'loop' ? dagNode.exit_expression : dagNode.expression,
        maxIterations: dagNode.max_iterations,
        tool: dagNode.tool,
        params: dagNode.params,
        status: 'idle',
      },
    } as FlowNode)

    if (kind === 'condition') {
      const branches = (dagNode.branches ?? {}) as Record<string, string | string[]>
      for (const target of asArray(branches.true)) pushEdge(dagNode.id, target, COND_TRUE)
      for (const target of asArray(branches.false)) pushEdge(dagNode.id, target, COND_FALSE)
    } else if (kind === 'parallel') {
      for (const target of asArray(dagNode.branches as string | string[])) pushEdge(dagNode.id, target)
    } else if (kind === 'loop') {
      if (dagNode.body_next) pushEdge(dagNode.id, dagNode.body_next, LOOP_BACK)
      for (const target of asArray(dagNode.next)) pushEdge(dagNode.id, target)
    } else {
      for (const target of asArray(dagNode.next)) pushEdge(dagNode.id, target)
    }
  }

  return { nodes, edges }
}

function asArray(value: string | string[] | null | undefined): string[] {
  if (!value) return []
  return Array.isArray(value) ? value : [value]
}
