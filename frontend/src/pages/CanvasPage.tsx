import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type OnSelectionChangeParams,
} from '@xyflow/react'
import { useLocation } from 'react-router-dom'
import { FlowEdge } from '../canvas/FlowEdge'
import { nodeTypes } from '../canvas/nodes'
import { Button } from '../components/Button'
import { agents } from '../data/snapshot'
import {
  briefings,
  clearLayout,
  defaultEdges,
  defaultNodes,
  loadNodes,
  palette,
  runScript,
  saveLayout,
  type FlowData,
  type FlowNode,
} from '../data/workflow'

const edgeTypes = { flow: FlowEdge }

function formatTimer(total: number) {
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function applyStep(nodes: FlowNode[], done: string[], running: string[]) {
  return nodes.map((item) => {
    let status = item.data.status
    let speech = item.data.speech
    let calls = item.data.calls
    if (done.includes(item.id)) {
      status = 'done'
      const brief = briefings[item.id]
      if (brief) {
        speech = brief.speech
        calls = brief.calls
      }
    }
    if (running.includes(item.id)) {
      status = 'running'
      const brief = briefings[item.id]
      if (brief && item.id === 'n11') {
        speech = brief.speech
        calls = brief.calls
      }
    }
    return { ...item, data: { ...item.data, status, speech, calls } }
  })
}

function CanvasEditor() {
  const location = useLocation()
  const armed = Boolean((location.state as { armed?: boolean } | null)?.armed)
  const { screenToFlowPosition, setCenter } = useReactFlow()
  const [nodes, setNodes, onNodesChange] = useNodesState(loadNodes())
  const [edges, setEdges, onEdgesChange] = useEdgesState(defaultEdges())
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [round, setRound] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [savedNote, setSavedNote] = useState('')
  const timers = useRef<number[]>([])
  const started = useRef(false)

  const selected = nodes.find((item) => item.id === selectedId) ?? null

  const stopTimers = useCallback(() => {
    timers.current.forEach((id) => {
      window.clearTimeout(id)
      window.clearInterval(id)
    })
    timers.current = []
  }, [])

  const startRun = useCallback(() => {
    stopTimers()
    followed.current = ''
    setRunning(true)
    setRound(1)
    setElapsed(0)
    setNodes((current) =>
      current.map((item) => ({
        ...item,
        data: {
          ...item.data,
          status: 'idle',
          speech: undefined,
          calls: undefined,
          remain: item.id === 'n10' ? 90 : undefined,
        },
      })),
    )
    const clock = window.setInterval(() => setElapsed((value) => value + 1), 1000)
    timers.current.push(clock)
    const later = (at: number, fn: () => void) => {
      const id = window.setTimeout(fn, at)
      timers.current.push(id)
    }
    runScript.forEach((step) => {
      later(step.at, () => setNodes((current) => applyStep(current, step.done, step.running)))
    })
    const waitTick = window.setInterval(() => {
      setNodes((current) =>
        current.map((item) => {
          if (item.id !== 'n10' || item.data.status !== 'running') return item
          const remain = Math.max(0, (item.data.remain ?? 90) - 15)
          return { ...item, data: { ...item.data, remain } }
        }),
      )
    }, 400)
    timers.current.push(waitTick)
    const say = (id: string, speech: string) => {
      setNodes((current) =>
        current.map((item) => (item.id === id ? { ...item, data: { ...item.data, speech } } : item)),
      )
    }
    later(10000, () => {
      setNodes((current) => applyStep(current, ['n10'], ['n11']))
    })
    later(11600, () => {
      setNodes((current) => applyStep(current, ['n11'], ['n11b']))
      say('n11b', '第 1 轮达成率 39.39%，低于 60%。按缺口补灌 20 秒，进入第 2 轮。')
    })
    later(13200, () => {
      setRound(2)
      setNodes((current) =>
        applyStep(current, ['n11b'], ['n9']).map((item) =>
          item.id === 'n10' ? { ...item, data: { ...item.data, remain: 90 } } : item,
        ),
      )
      say('n9', '【执行反馈】补灌任务已下发：k10-act-03 浇水 20 秒。设备状态：在线。')
    })
    later(14800, () => {
      setNodes((current) =>
        applyStep(current, ['n9'], ['n10']).map((item) =>
          item.id === 'n10' ? { ...item, data: { ...item.data, remain: 90, status: 'running' } } : item,
        ),
      )
    })
    later(17200, () => {
      setNodes((current) => applyStep(current, ['n10'], ['n11']))
      say(
        'n11',
        '【验证报告】第 2 轮：基线 45.0% → 复测 57.0%，目标 [55,65]，达成率 100.00%，置信度 100.00%。结论：闭环成功。',
      )
    })
    later(18800, () => {
      window.clearInterval(waitTick)
      window.clearInterval(clock)
      setRunning(false)
      setNodes((current) =>
        applyStep(current, ['n11', 'n13'], []).map((item) =>
          item.id === 'n11'
            ? {
                ...item,
                data: {
                  ...item.data,
                  speech:
                    '【验证报告】第 2 轮：基线 45.0% → 复测 57.0%，目标 [55,65]，达成率 100.00%，置信度 100.00%。结论：闭环成功。',
                },
              }
            : item,
        ),
      )
    })
  }, [setNodes, stopTimers])

  useEffect(() => {
    if (!armed || started.current) return
    started.current = true
    startRun()
  }, [armed, startRun])

  const followed = useRef('')

  useEffect(() => {
    const active = nodes.filter((item) => item.data.status === 'running')
    const key = active.map((item) => item.id).join(',')
    if (!key || key === followed.current) return
    followed.current = key
    const minX = Math.min(...active.map((item) => item.position.x))
    const maxX = Math.max(...active.map((item) => item.position.x)) + 180
    const minY = Math.min(...active.map((item) => item.position.y))
    const maxY = Math.max(...active.map((item) => item.position.y)) + 72
    setCenter((minX + maxX) / 2, (minY + maxY) / 2, { zoom: 0.9, duration: 400 })
  }, [nodes, setCenter])

  useEffect(() => () => stopTimers(), [stopTimers])

  useEffect(() => {
    setEdges((current) => {
      let changed = false
      const status = new Map(nodes.map((item) => [item.id, item.data.status]))
      const next = current.map((edge) => {
        const source = status.get(edge.source)
        const target = status.get(edge.target)
        const active = (source === 'done' && target === 'running') || (source === 'running' && target === 'running')
        if (edge.data?.active === active) return edge
        changed = true
        return { ...edge, data: { ...edge.data, active } }
      })
      return changed ? next : current
    })
  }, [nodes, setEdges])

  const onDragStart = (event: DragEvent, type: string, data: Omit<FlowData, 'status'>) => {
    event.dataTransfer.setData('application/zhiqiu-node', JSON.stringify({ type, data }))
    event.dataTransfer.effectAllowed = 'move'
  }

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    const raw = event.dataTransfer.getData('application/zhiqiu-node')
    if (!raw) return
    const dropped = JSON.parse(raw) as { type: FlowData['kind']; data: Omit<FlowData, 'status'> }
    const position = screenToFlowPosition({ x: event.clientX, y: event.clientY })
    const id = `extra-${Date.now()}`
    setNodes((current) =>
      current.concat({
        id,
        type: dropped.type,
        position,
        data: { ...dropped.data, status: 'idle' },
      }),
    )
    setSelectedId(id)
  }

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return
      setEdges((current) =>
        current.concat({
          id: `e-${Date.now()}`,
          source: connection.source,
          target: connection.target,
          sourceHandle: connection.sourceHandle,
          targetHandle: connection.targetHandle,
          type: 'flow',
          data: { active: false },
        }),
      )
    },
    [setEdges],
  )

  const onSelectionChange = useCallback(({ nodes: picked }: OnSelectionChangeParams) => {
    setSelectedId(picked[0]?.id ?? null)
  }, [])

  const patchSelected = (patch: Partial<FlowData>) => {
    if (!selectedId) return
    setNodes((current) =>
      current.map((item) => (item.id === selectedId ? { ...item, data: { ...item.data, ...patch } } : item)),
    )
    setSavedNote('配置已写在这个节点上。')
  }

  return (
    <div className="page-enter -mt-3 flex min-h-[640px] flex-1 flex-col gap-3 lg:h-full lg:min-h-0">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-medium leading-none">工作流</h1>
          <p className="mt-1 text-sm text-dim">默认流程「巡园浇水」。土壤湿度 38.5%，决策走浇水分支。</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-sm text-dim" htmlFor="workflow">
            工作流
          </label>
          <select id="workflow" className="h-11 rounded-btn border border-line bg-panel px-3 text-sm" defaultValue="patrol">
            <option value="patrol">巡园浇水</option>
          </select>
          <span className="num inline-flex h-11 items-center rounded-btn border border-line bg-panel px-3 text-sm">{formatTimer(elapsed)}</span>
          <span className="inline-flex h-11 items-center gap-2 rounded-btn border border-line bg-panel px-3 text-sm">
            <span className="h-2 w-2 rounded-full bg-[#E4B423]" aria-hidden="true" />
            {round === 0 ? '未开始' : `第 ${round} 轮`}
          </span>
          {running ? (
            <Button
              tone="ghost"
              onClick={() => {
                stopTimers()
                setRunning(false)
              }}
            >
              停止运行
            </Button>
          ) : (
            <Button onClick={startRun}>运行工作流</Button>
          )}
        </div>
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[200px_minmax(0,1fr)_300px]">
        <aside className="rounded-card border border-line bg-panel p-3">
          <h2 className="px-1 text-sm font-medium">节点</h2>
          <ul className="mt-2 grid gap-2">
            {palette.map((item) => (
              <li key={item.type}>
                <button
                  type="button"
                  draggable
                  onDragStart={(event) => onDragStart(event, item.type, item.data)}
                  className="flex h-14 w-full flex-col items-start justify-center rounded-btn border border-line px-3 text-left hover:-translate-y-0.5"
                >
                  <span className="text-sm text-paper">{item.label}</span>
                  <span className="text-[12px] text-dim">{item.hint}</span>
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-3 grid gap-2">
            <Button
              tone="ghost"
              onClick={() => {
                saveLayout(nodes)
                setSavedNote('布局已留在这台浏览器里，刷新后还在。')
              }}
            >
              保存布局
            </Button>
            <Button
              tone="ghost"
              onClick={() => {
                stopTimers()
                setRunning(false)
                clearLayout()
                setNodes(defaultNodes())
                setEdges(defaultEdges())
                setRound(0)
                setElapsed(0)
                setSavedNote('已回到默认布局。')
              }}
            >
              恢复默认
            </Button>
          </div>
          {savedNote ? <p className="mt-3 px-1 text-[13px] text-dim">{savedNote}</p> : null}
        </aside>
        <div
          className="min-h-[480px] overflow-hidden rounded-card border border-line bg-panel"
          onDragOver={(event) => event.preventDefault()}
          onDrop={onDrop}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onSelectionChange={onSelectionChange}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            defaultViewport={{ x: 8, y: 24, zoom: 0.78 }}
            minZoom={0.35}
            maxZoom={1.4}
            deleteKeyCode={['Backspace', 'Delete']}
          >
            <Background color="#D5E6DA" gap={18} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable maskColor="rgba(244,247,242,0.7)" />
          </ReactFlow>
        </div>
        <Inspector node={selected} onSave={patchSelected} />
      </div>
    </div>
  )
}

function Inspector({ node, onSave }: { node: FlowNode | null; onSave: (patch: Partial<FlowData>) => void }) {
  const [draft, setDraft] = useState<Partial<FlowData>>({})

  useEffect(() => {
    if (!node) {
      setDraft({})
      return
    }
    setDraft({
      name: node.data.name,
      agentKey: node.data.agentKey,
      input: node.data.input ?? '',
      expression: node.data.expression ?? '',
      maxIterations: node.data.maxIterations,
    })
  }, [node])

  if (!node) {
    return (
      <aside className="rounded-card border border-line bg-panel p-4">
        <h2 className="text-sm font-medium">节点配置</h2>
        <p className="mt-3 text-sm text-dim">点一个节点，可以改输入、表达式，并看这一步的发言。</p>
      </aside>
    )
  }

  const kind = node.data.kind
  return (
    <aside className="overflow-auto rounded-card border border-line bg-panel p-4">
      <h2 className="text-sm font-medium">{node.data.name}</h2>
      <p className="mt-1 text-[13px] text-dim">
        {node.id} · {kind}
      </p>
      <form
        className="mt-4 grid gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          onSave(draft)
        }}
      >
        <label className="grid gap-1 text-sm">
          名称
          <input
            className="h-11 rounded-btn border border-line px-3"
            value={draft.name ?? ''}
            onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
          />
        </label>
        {kind === 'agent' ? (
          <label className="grid gap-1 text-sm">
            智能体
            <select
              className="h-11 rounded-btn border border-line px-3"
              value={draft.agentKey ?? 'scout'}
              onChange={(event) => setDraft((current) => ({ ...current, agentKey: event.target.value }))}
            >
              {agents.map((agent) => (
                <option key={agent.key} value={agent.key}>
                  {agent.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        {kind === 'agent' || kind === 'tool' ? (
          <label className="grid gap-1 text-sm">
            输入
            <textarea
              className="min-h-24 rounded-btn border border-line px-3 py-2"
              value={draft.input ?? ''}
              onChange={(event) => setDraft((current) => ({ ...current, input: event.target.value }))}
            />
          </label>
        ) : null}
        {kind === 'condition' || kind === 'loop' ? (
          <label className="grid gap-1 text-sm">
            表达式
            <textarea
              className="min-h-20 rounded-btn border border-line px-3 py-2 font-mono text-[13px]"
              value={draft.expression ?? ''}
              onChange={(event) => setDraft((current) => ({ ...current, expression: event.target.value }))}
            />
          </label>
        ) : null}
        {kind === 'loop' ? (
          <label className="grid gap-1 text-sm">
            最多轮次
            <input
              type="number"
              min={1}
              className="h-11 rounded-btn border border-line px-3"
              value={draft.maxIterations ?? 2}
              onChange={(event) => setDraft((current) => ({ ...current, maxIterations: Number(event.target.value) }))}
            />
          </label>
        ) : null}
        <Button type="submit">保存配置</Button>
      </form>
      <div className="mt-5 border-t border-line pt-4">
        <h3 className="text-sm font-medium">这一步的发言</h3>
        <p className="mt-2 text-sm leading-6 text-paper">{node.data.speech ?? '还没有跑到这一步。'}</p>
        {node.data.calls?.length ? (
          <ul className="mt-3 grid gap-2">
            {node.data.calls.map((call) => (
              <li key={call.name} className="rounded-btn bg-ink px-3 py-2 text-[13px]">
                <span className="block font-medium text-paper">{call.name}</span>
                <span className="mt-1 block text-dim">{call.detail}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </aside>
  )
}

export function CanvasPage() {
  return (
    <ReactFlowProvider>
      <CanvasEditor />
    </ReactFlowProvider>
  )
}
