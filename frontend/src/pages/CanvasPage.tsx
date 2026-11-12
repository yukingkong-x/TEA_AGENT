import { PageFrame } from '../components/PageFrame'
import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import {
  Background,
  BackgroundVariant,
  ConnectionLineType,
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
  const { screenToFlowPosition, setCenter, setViewport, zoomTo } = useReactFlow()
  const [nodes, setNodes, onNodesChange] = useNodesState(loadNodes())
  const [edges, setEdges, onEdgesChange] = useEdgesState(defaultEdges())
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [round, setRound] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [savedNote, setSavedNote] = useState('改动保存在这台浏览器')
  const [zoom, setZoom] = useState(0.85)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null)
  const timers = useRef<number[]>([])
  const started = useRef(false)
  const paneRef = useRef<HTMLDivElement>(null)

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
      setNodes((current) =>
        applyStep(current, ['n11'], ['n11b']).map((item) => {
          if (item.id === 'n11') return { ...item, data: { ...item.data, status: 'failed' } }
          if (item.id === 'n11b') {
            return {
              ...item,
              data: {
                ...item.data,
                speech: '第 1 轮达成率 39.39%，低于 60%。按缺口补灌 20 秒，进入第 2 轮。',
              },
            }
          }
          return item
        }),
      )
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
    const maxX = Math.max(...active.map((item) => item.position.x)) + 240
    const minY = Math.min(...active.map((item) => item.position.y))
    const maxY = Math.max(...active.map((item) => item.position.y)) + 84
    setCenter((minX + maxX) / 2, (minY + maxY) / 2, { zoom: 0.78, duration: 400 })
  }, [nodes, setCenter])

  useEffect(() => () => stopTimers(), [stopTimers])

  useEffect(() => {
    setEdges((current) => {
      let changed = false
      const status = new Map(nodes.map((item) => [item.id, item.data.status]))
      const next = current.map((edge) => {
        const source = status.get(edge.source)
        const target = status.get(edge.target)
        const passed = source === 'done' || source === 'failed'
        const active = (passed && target === 'running') || (source === 'running' && target === 'running')
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

  const placeNode = (type: FlowData['kind'], data: Omit<FlowData, 'status'>) => {
    const bounds = paneRef.current?.getBoundingClientRect()
    const position = bounds
      ? screenToFlowPosition({
          x: bounds.left + bounds.width / 2 - 90,
          y: bounds.top + bounds.height / 2 - 24,
        })
      : { x: 240, y: 180 }
    const id = `extra-${Date.now()}`
    setNodes((current) =>
      current.concat({
        id,
        type,
        position,
        data: { ...data, status: 'idle' },
      }),
    )
    setSelectedId(id)
    setPickerOpen(false)
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
    const next = nodes.map((item) => (item.id === selectedId ? { ...item, data: { ...item.data, ...patch } } : item))
    setNodes(next)
    saveLayout(next)
    setSavedNote('配置已写在这个节点上，刷新后还在。')
  }

  const removeNode = (id: string) => {
    setNodes((current) => current.filter((item) => item.id !== id))
    setEdges((current) => current.filter((edge) => edge.source !== id && edge.target !== id))
    if (selectedId === id) setSelectedId(null)
    setMenu(null)
    setSavedNote('已删除这个模块')
  }

  const copyNode = (id: string) => {
    const source = nodes.find((item) => item.id === id)
    if (!source) return
    const nextId = `extra-${Date.now()}`
    setNodes((current) =>
      current.concat({
        id: nextId,
        type: source.type,
        position: { x: source.position.x + 32, y: source.position.y + 32 },
        data: { ...source.data, status: 'idle', speech: undefined, calls: undefined },
      }),
    )
    setSelectedId(nextId)
    setMenu(null)
    setSavedNote('已复制到旁边')
  }

  const shown = palette.filter((item) => {
    const word = query.trim()
    if (!word) return true
    return item.label.includes(word) || item.hint.includes(word)
  })

  return (
    <div
      ref={paneRef}
      className="relative h-full min-h-[640px] min-w-0 flex-1 bg-[#F6F7FB]"
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
          onPaneClick={() => {
            setPickerOpen(false)
            setMenu(null)
          }}
          onNodeContextMenu={(event, node) => {
            event.preventDefault()
            const bounds = paneRef.current?.getBoundingClientRect()
            if (!bounds) return
            const width = 144
            const height = 84
            setMenu({
              id: node.id,
              x: Math.max(8, Math.min(event.clientX - bounds.left, bounds.width - width - 8)),
              y: Math.max(8, Math.min(event.clientY - bounds.top, bounds.height - height - 8)),
            })
            setSelectedId(node.id)
            setPickerOpen(false)
          }}
          onMove={(_, viewport) => {
            setZoom(viewport.zoom)
            setMenu(null)
          }}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          defaultViewport={{ x: 120, y: 16, zoom: 0.85 }}
          connectionLineType={ConnectionLineType.Bezier}
          minZoom={0.35}
          maxZoom={1.4}
          deleteKeyCode={['Backspace', 'Delete']}
        >
          <Background variant={BackgroundVariant.Dots} color="#D5D8E2" gap={22} size={1.35} />
          <MiniMap pannable zoomable maskColor="rgba(246,247,251,0.72)" className="!bottom-20" />
        </ReactFlow>

        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-between gap-3 px-4 py-3">
          <div className="pointer-events-auto min-w-0">
            <p className="truncate text-[20px] font-medium leading-[1.3] text-paper">巡园浇水</p>
            <p className="mt-0.5 truncate text-xs leading-none text-mute">{savedNote}</p>
          </div>
          <div className="pointer-events-auto flex shrink-0 items-center gap-2">
            <span className="num inline-flex h-9 items-center rounded-btn bg-panel px-3 text-xs leading-none text-paper shadow-[0_6px_20px_rgba(23,33,27,0.06)]">
              {formatTimer(elapsed)}
            </span>
            <span className="inline-flex h-9 items-center gap-2 rounded-btn bg-panel px-3 text-xs leading-none text-paper shadow-[0_6px_20px_rgba(23,33,27,0.06)]">
              <span className="h-2 w-2 rounded-full bg-[#E4B423]" aria-hidden="true" />
              {round === 0 ? '未开始' : `第 ${round} 轮`}
            </span>
            <button
              type="button"
              className="h-11 rounded-btn bg-panel px-3 text-base text-dim shadow-[0_6px_20px_rgba(23,33,27,0.06)]"
              onClick={() => {
                saveLayout(nodes)
                setSavedNote('已保存在这台浏览器')
              }}
            >
              保存
            </button>
            <button
              type="button"
              className="h-11 rounded-btn bg-panel px-3 text-base text-dim shadow-[0_6px_20px_rgba(23,33,27,0.06)]"
              onClick={() => {
                stopTimers()
                setRunning(false)
                clearLayout()
                setNodes(defaultNodes())
                setEdges(defaultEdges())
                setRound(0)
                setElapsed(0)
                setViewport({ x: 120, y: 16, zoom: 0.85 }, { duration: 280 })
                setSavedNote('已回到默认布局')
              }}
            >
              恢复默认
            </button>
          </div>
        </div>

        {pickerOpen ? (
          <div className="absolute bottom-20 left-1/2 z-30 w-[min(440px,calc(100%-32px))] -translate-x-1/2 rounded-card border border-line bg-panel p-4 shadow-[0_16px_40px_rgba(23,33,27,0.12)]">
            <p className="text-[24px] font-medium leading-[1.3] text-paper">添加节点</p>
            <input
              className="mt-3 h-10 w-full rounded-btn border border-line bg-[#F6F7FB] px-3 text-base"
              placeholder="搜索节点"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <p className="mt-4 text-xs leading-none text-mute">业务逻辑</p>
            {shown.length === 0 ? (
              <p className="py-6 text-center text-xs leading-normal text-mute">没有叫这个的节点。</p>
            ) : (
              <ul className="mt-2 grid grid-cols-2 gap-2">
                {shown.map((item) => (
                  <li key={item.type}>
                    <button
                      type="button"
                      draggable
                      onDragStart={(event) => onDragStart(event, item.type, item.data)}
                      onClick={() => placeNode(item.type, item.data)}
                      className="flex h-12 w-full items-center gap-2 rounded-btn px-2 text-left hover:bg-[#F6F7FB]"
                    >
                      <NodeGlyph type={item.type} />
                      <span className="min-w-0">
                        <span className="block truncate text-sm leading-normal text-paper">{item.label}</span>
                        <span className="block truncate text-xs leading-none text-mute">{item.hint}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        <div className="absolute bottom-4 left-1/2 z-30 flex -translate-x-1/2 items-center gap-1 rounded-full border border-line bg-panel p-1.5 shadow-[0_10px_30px_rgba(23,33,27,0.1)]">
          <button type="button" className="num h-10 rounded-full px-3 text-base text-paper" onClick={() => zoomTo(1)}>
            {Math.round(zoom * 100)}%
          </button>
          <button type="button" className="h-10 rounded-full px-3 text-base text-dim" onClick={() => zoomTo(Math.max(0.35, zoom - 0.1))}>
            缩小
          </button>
          <button type="button" className="h-10 rounded-full px-3 text-base text-dim" onClick={() => zoomTo(Math.min(1.4, zoom + 0.1))}>
            放大
          </button>
          <button
            type="button"
            aria-expanded={pickerOpen}
            className="h-10 rounded-full bg-tea px-4 text-base text-white hover:bg-teaHover active:bg-teaPress"
            onClick={() => setPickerOpen((open) => !open)}
          >
            + 添加节点
          </button>
          {running ? (
            <button
              type="button"
              className="h-10 rounded-full bg-[#FFECE8] px-4 text-base text-danger"
              onClick={() => {
                stopTimers()
                setRunning(false)
              }}
            >
              停止
            </button>
          ) : (
            <button type="button" className="h-10 rounded-full bg-tea px-4 text-base text-white hover:bg-teaHover active:bg-teaPress" onClick={startRun}>
              试运行
            </button>
          )}
        </div>

        {menu ? (
          <div
            role="menu"
            className="absolute z-40 w-36 overflow-hidden rounded-xl border border-[#EEF0F3] bg-panel py-1 shadow-[0_12px_32px_rgba(22,28,45,0.12)]"
            style={{ left: menu.x, top: menu.y }}
          >
            <button
              type="button"
              role="menuitem"
              className="flex h-11 w-full items-center px-3 text-left text-base text-paper hover:bg-[#F6F7FB]"
              onClick={() => copyNode(menu.id)}
            >
              复制
            </button>
            <button
              type="button"
              role="menuitem"
              className="flex h-11 w-full items-center px-3 text-left text-base text-danger hover:bg-[#FFECE8]"
              onClick={() => removeNode(menu.id)}
            >
              删除
            </button>
          </div>
        ) : null}

        <Inspector
          node={selected}
          onSave={patchSelected}
          onClose={() => {
            setSelectedId(null)
            setNodes((current) => current.map((item) => ({ ...item, selected: false })))
          }}
        />
      </div>
  )
}

function NodeGlyph({ type }: { type: string }) {
  const wash = type === 'parallel' ? 'bg-[#FFF4CC]' : 'bg-panel2'
  return (
    <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${wash}`} aria-hidden="true">
      {type === 'agent' ? <span className="h-3 w-3 rounded-full bg-tea" /> : null}
      {type === 'condition' ? <span className="h-3 w-3 rotate-45 border-2 border-tea" /> : null}
      {type === 'parallel' ? <span className="h-0.5 w-4 bg-[#8A6414]" /> : null}
      {type === 'loop' ? <span className="h-3.5 w-3.5 rounded-full border-2 border-tea" /> : null}
    </span>
  )
}

function Inspector({
  node,
  onSave,
  onClose,
}: {
  node: FlowNode | null
  onSave: (patch: Partial<FlowData>) => void
  onClose: () => void
}) {
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

  if (!node) return null

  const kind = node.data.kind
  return (
    <aside className="absolute bottom-0 right-0 top-0 z-20 w-[min(100%,320px)] overflow-auto border-l border-line bg-panel px-4 py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-paper">{node.data.name}</h2>
          <p className="num mt-1 text-xs leading-none text-mute">
            {node.id} · {kind}
          </p>
        </div>
        <button type="button" className="h-11 shrink-0 rounded-btn px-3 text-base text-dim" onClick={onClose}>
          关闭
        </button>
      </div>
      <form
        className="mt-4 grid gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          onSave(draft)
        }}
      >
        <label className="grid gap-1 text-base">
          名称
          <input
            className="h-11 rounded-btn border border-line px-3"
            value={draft.name ?? ''}
            onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
          />
        </label>
        {kind === 'agent' ? (
          <label className="grid gap-1 text-base">
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
          <label className="grid gap-1 text-base">
            输入
            <textarea
              className="min-h-24 rounded-btn border border-line px-3 py-2"
              value={draft.input ?? ''}
              onChange={(event) => setDraft((current) => ({ ...current, input: event.target.value }))}
            />
          </label>
        ) : null}
        {kind === 'condition' || kind === 'loop' ? (
          <label className="grid gap-1 text-base">
            表达式
            <textarea
              className="num min-h-20 rounded-btn border border-line px-3 py-2 text-base"
              value={draft.expression ?? ''}
              onChange={(event) => setDraft((current) => ({ ...current, expression: event.target.value }))}
            />
          </label>
        ) : null}
        {kind === 'loop' ? (
          <label className="grid gap-1 text-base">
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
        <h3 className="text-paper">这一步的发言</h3>
        <p className="mt-2 text-sm leading-normal text-paper">{node.data.speech ?? '还没有跑到这一步。'}</p>
        {node.data.calls?.length ? (
          <ul className="mt-3 grid gap-2">
            {node.data.calls.map((call) => (
              <li key={call.name} className="rounded-btn bg-ink px-3 py-2 text-sm leading-normal">
                <span className="block text-paper">{call.name}</span>
                <span className="mt-1 block text-mute">{call.detail}</span>
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
    <PageFrame title="画布" fill>
      <ReactFlowProvider>
        <CanvasEditor />
      </ReactFlowProvider>
    </PageFrame>
  )
}
