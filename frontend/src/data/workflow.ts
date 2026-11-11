import type { Edge, Node } from '@xyflow/react'

export type RunStatus = 'idle' | 'running' | 'done' | 'failed'

export type FlowData = {
  name: string
  kind: 'start' | 'end' | 'agent' | 'parallel' | 'condition' | 'tool' | 'loop'
  agentKey?: string
  input?: string
  expression?: string
  maxIterations?: number
  tool?: string
  remain?: number
  loopOut?: boolean
  status: RunStatus
  speech?: string
  calls?: { name: string; detail: string }[]
}

export type FlowNode = Node<FlowData>
export type FlowEdge = Edge<{ active?: boolean }>

const LAYOUT_KEY = 'zhiqiu.canvas.layout'

type SavedNode = {
  id: string
  type?: string
  position: { x: number; y: number }
  name?: string
  input?: string
  expression?: string
  agentKey?: string
  maxIterations?: number
}

function node(
  id: string,
  type: FlowData['kind'],
  position: { x: number; y: number },
  data: Omit<FlowData, 'status' | 'kind'> & { kind?: FlowData['kind'] },
): FlowNode {
  return {
    id,
    type,
    position,
    data: { status: 'idle', kind: type, ...data },
  }
}

export function defaultNodes(): FlowNode[] {
  return [
    node('n1', 'start', { x: 0, y: 250 }, { name: '开始' }),
    node('n2', 'agent', { x: 180, y: 228 }, {
      name: '巡园播报',
      agentKey: 'scout',
      input: '开始本轮巡园，目标区域：A区茶垄。',
    }),
    node('n3', 'parallel', { x: 430, y: 236 }, { name: '三方会诊' }),
    node('n4', 'agent', { x: 680, y: 40 }, {
      name: '气象评估',
      agentKey: 'weather',
      input: '评估未来12小时天气对A区灌溉的影响。',
    }),
    node('n5', 'agent', { x: 680, y: 220 }, {
      name: '墒情分析',
      agentKey: 'soil',
      input: '分析A区土壤墒情并评级。',
    }),
    node('n6', 'agent', { x: 680, y: 400 }, {
      name: '植保核查',
      agentKey: 'pest',
      input: '核查当前墒情下灌溉的农艺风险。',
    }),
    node('n7', 'agent', { x: 980, y: 220 }, {
      name: '灌溉决策',
      agentKey: 'decision',
      input: '汇总三方结论与本轮巡园播报，按决策树给出决策。',
    }),
    node('n8', 'condition', { x: 1260, y: 200 }, {
      name: '决策分流',
      expression: "context.last_decision == 'irrigate'",
    }),
    node('n9', 'agent', { x: 1540, y: 40 }, {
      name: '执行浇水',
      agentKey: 'executor',
      input: '领取设备指令任务并执行，跟踪回执直到完成或熔断。',
    }),
    node('n10', 'tool', { x: 1820, y: 40 }, {
      name: '渗透等待',
      tool: 'wait_penetration',
      input: '浇水结束后等待 90 秒再复测。',
      remain: 90,
    }),
    node('n11', 'agent', { x: 2100, y: 40 }, {
      name: '验证审计',
      agentKey: 'verifier',
      loopOut: true,
      input: '对刚完成的浇水任务执行复测验证，不达标启动 Self-Loop。',
    }),
    node('n11b', 'loop', { x: 2100, y: 230 }, {
      name: 'Self-Loop',
      maxIterations: 2,
      expression: "context.last_verification == 'success' or context.round > 2",
    }),
    node('n12', 'agent', { x: 1540, y: 400 }, {
      name: '无需作业归档',
      agentKey: 'verifier',
      input: '本轮决策为暂不作业，生成简要记录。',
    }),
    node('n13', 'end', { x: 2420, y: 236 }, { name: '结束' }),
  ]
}

export function defaultEdges(): FlowEdge[] {
  const link = (
    id: string,
    source: string,
    target: string,
    extra?: Partial<FlowEdge>,
  ): FlowEdge => ({
    id,
    source,
    target,
    type: 'flow',
    data: { active: false },
    ...extra,
  })
  return [
    link('e1', 'n1', 'n2'),
    link('e2', 'n2', 'n3'),
    link('e3', 'n3', 'n4'),
    link('e4', 'n3', 'n5'),
    link('e5', 'n3', 'n6'),
    link('e6', 'n4', 'n7'),
    link('e7', 'n5', 'n7'),
    link('e8', 'n6', 'n7'),
    link('e9', 'n7', 'n8'),
    link('e10', 'n8', 'n9', { sourceHandle: 'yes', label: '浇水' }),
    link('e11', 'n8', 'n12', { sourceHandle: 'no', label: '不浇' }),
    link('e12', 'n9', 'n10'),
    link('e13', 'n10', 'n11'),
    link('e14', 'n11', 'n13'),
    link('e15', 'n11', 'n11b', { sourceHandle: 'loop', label: '未达标' }),
    link('e16', 'n11b', 'n11', { label: '再验证' }),
    link('e17', 'n12', 'n13'),
  ]
}

export function loadNodes(): FlowNode[] {
  const base = defaultNodes()
  try {
    const raw = localStorage.getItem(LAYOUT_KEY)
    if (!raw) return base
    const saved = JSON.parse(raw) as SavedNode[]
    if (!Array.isArray(saved)) return base
    const known = new Set(base.map((item) => item.id))
    const merged = base.map((item) => {
      const found = saved.find((entry) => entry.id === item.id)
      if (!found) return item
      return {
        ...item,
        position: found.position ?? item.position,
        data: {
          ...item.data,
          name: found.name ?? item.data.name,
          input: found.input ?? item.data.input,
          expression: found.expression ?? item.data.expression,
          agentKey: found.agentKey ?? item.data.agentKey,
          maxIterations: found.maxIterations ?? item.data.maxIterations,
        },
      }
    })
    const extras = saved
      .filter((entry) => !known.has(entry.id) && entry.type && entry.position)
      .map((entry) =>
        node(entry.id, entry.type as FlowData['kind'], entry.position, {
          name: entry.name || '未命名',
          input: entry.input,
          expression: entry.expression,
          agentKey: entry.agentKey,
          maxIterations: entry.maxIterations,
        }),
      )
    return merged.concat(extras)
  } catch {
    return base
  }
}

export function saveLayout(nodes: FlowNode[]) {
  const payload: SavedNode[] = nodes.map((item) => ({
    id: item.id,
    type: item.type,
    position: item.position,
    name: item.data.name,
    input: item.data.input,
    expression: item.data.expression,
    agentKey: item.data.agentKey,
    maxIterations: item.data.maxIterations,
  }))
  localStorage.setItem(LAYOUT_KEY, JSON.stringify(payload))
}

export function clearLayout() {
  localStorage.removeItem(LAYOUT_KEY)
}

export const runScript: { at: number; done: string[]; running: string[] }[] = [
  { at: 0, done: [], running: ['n1'] },
  { at: 500, done: ['n1'], running: ['n2'] },
  { at: 1700, done: ['n2'], running: ['n3', 'n4', 'n5', 'n6'] },
  { at: 3600, done: ['n3', 'n4', 'n5', 'n6'], running: ['n7'] },
  { at: 5200, done: ['n7'], running: ['n8'] },
  { at: 6000, done: ['n8'], running: ['n9'] },
  { at: 7600, done: ['n9'], running: ['n10'] },
]

export const briefings: Record<string, { speech: string; calls?: { name: string; detail: string }[] }> = {
  n2: {
    speech:
      '【巡园播报】A区茶垄：气温 24.6℃，空气湿度 63.2%，光照 1250 lx，土壤湿度 38.5%。预警：土壤湿度低于 40%。请气象员、土壤师、植保员评估是否有作业需求。',
    calls: [
      { name: 'get_env_status', detail: 'k10-field-01 → 24.6℃ / 63.2% / 1250 lx' },
      { name: 'get_soil_status', detail: 'esp32-soil-02 → 38.5%，趋势下降' },
      { name: 'raise_alert', detail: 'warning：土壤湿度低于 40%' },
    ],
  },
  n4: {
    speech: '【气象评估】未来 12 小时天气数据不可用。结论：数据不可用。',
    calls: [{ name: 'get_weather', detail: 'A区 → 数据不可用' }],
  },
  n5: {
    speech: '【墒情报告】A区土壤湿度 38.5%，趋势下降，评级：轻度缺水。建议：建议灌溉，目标湿度区间 55%-65%。',
    calls: [{ name: 'get_soil_status', detail: '38.5%，连续下降，低于 40%' }],
  },
  n6: {
    speech: '【植保核查】知识库中未检索到相关内容。风险：无。建议：无冲突。',
    calls: [{ name: 'query_knowledge', detail: '命中 0 条' }],
  },
  n7: {
    speech:
      '【决策】本轮决策：irrigate。方案：对 A区执行浇水 30 秒，目标湿度 55-65%，优先级 6。依据：土壤师评为轻度缺水，气象评估为数据不可用。',
    calls: [{ name: 'create_task', detail: 'device_cmd pump 30 秒，优先级 6，基线 38.5%' }],
  },
  n8: {
    speech: "context.last_decision == 'irrigate'，走浇水分支。",
  },
  n9: {
    speech: '【执行反馈】任务 task-1101：已下发，设备已接收，执行中。设备状态：在线。',
    calls: [{ name: 'send_device_cmd', detail: 'k10-act-03 pump 30 秒 → received' }],
  },
  n10: {
    speech: '渗透等待 90 秒。到点后才把流程交给验证审计官。',
    calls: [{ name: 'wait_penetration', detail: 'seconds = 90' }],
  },
  n11: {
    speech:
      '【验证报告】第 1 轮：基线 38.5% → 复测 45.0%，目标 [55,65]，达成率 39.39%，置信度 100.00%。结论：未达标，补灌 20 秒后再验。',
  },
}

export const palette = [
  {
    type: 'agent' as const,
    label: '智能体',
    hint: '拖进画布',
    data: { name: '新智能体', kind: 'agent' as const, agentKey: 'scout', input: '' },
  },
  {
    type: 'condition' as const,
    label: '判断',
    hint: '真假两条出边',
    data: { name: '新判断', kind: 'condition' as const, expression: "context.last_decision == 'irrigate'" },
  },
  {
    type: 'parallel' as const,
    label: '并行',
    hint: '同时跑多路',
    data: { name: '新并行', kind: 'parallel' as const },
  },
  {
    type: 'loop' as const,
    label: '循环',
    hint: '带次数上限',
    data: { name: '新循环', kind: 'loop' as const, maxIterations: 2, expression: '' },
  },
]
