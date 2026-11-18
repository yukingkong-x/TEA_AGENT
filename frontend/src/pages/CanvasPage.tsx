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
  type Edge,
  type OnSelectionChangeParams,
} from '@xyflow/react'
import { useLocation } from 'react-router-dom'
import { FlowEdge } from '../canvas/FlowEdge'
import { nodeTypes } from '../canvas/nodes'
import { Button } from '../components/Button'
import { RunChatDrawer } from '../components/RunChatDrawer'
import { ApiError } from '../api/client'
import { fromDagJson, toDagJson } from '../api/dag'
import { endpoints } from '../api/endpoints'
import { dashboardSocket } from '../api/socket'
import type { NodeStateEventDto, RunStatusEventDto, WorkflowDto } from '../api/types'
import { agents } from '../data/snapshot'
import {
  defaultEdges,
  defaultNodes,
  palette,
  type FlowData,
  type FlowNode,
  type RunStatus,
} from '../data/workflow'

const edgeTypes = { flow: FlowEdge }

/**
 * Self-Loop 的 body 入口（dag_json.body_next 指向的节点）。
 * 一轮修正会把 body 整段重走（n9 建单 → n10 渗透 → n11 复验），
 * 所以轮次只能按「回到入口」计，不能按「节点重复」计。
 */
function resolveBodyEntry(nodes: FlowNode[], edges: Edge[]): string | null {
  const loop = nodes.find((item) => item.data.kind === 'loop')
  if (!loop) return null
  const back = edges.find((edge) => edge.source === loop.id && edge.sourceHandle === 'back')
  return back?.target ?? null
}

function formatTimer(total: number) {
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function errText(err: unknown) {
  if (err instanceof ApiError) return err.notReady ? '模块接入中（SEAM_NOT_READY）' : err.message
  return err instanceof Error ? err.message : String(err)
}

/** 运行对话抽屉的开关记在本地：录屏时按自己习惯定一次，之后每次进来都保持 */
const DRAWER_KEY = 'zhiqiu.canvas.drawer'

function readDrawerPref(): boolean {
  try {
    const saved = window.localStorage.getItem(DRAWER_KEY)
    if (saved !== null) return saved === '1'
  } catch {
    /* 隐私模式读不到 localStorage，退回按屏宽判断 */
  }
  return window.innerWidth >= 1280
}

/** 节点事件 → 画布状态。按 state 点亮/熄灭，按 status 定红绿（contract 第 7 节）。 */
function applyNodeEvent(nodes: FlowNode[], event: NodeStateEventDto): FlowNode[] {
  return nodes.map((item) => {
    if (item.id !== event.node_id) return item
    if (event.state === 'started') {
      return { ...item, data: { ...item.data, status: 'running', speech: undefined, calls: undefined } }
    }
    const status: RunStatus =
      event.status === 'failed' ? 'failed' : event.status === 'skipped' ? 'idle' : 'done'
    return {
      ...item,
      data: {
        ...item.data,
        status,
        speech: event.output || item.data.speech,
        calls: toCalls(event.tool_calls) ?? item.data.calls,
        remain: undefined,
      },
    }
  })
}

function toCalls(raw: unknown): { name: string; detail: string }[] | undefined {
  if (!Array.isArray(raw) || raw.length === 0) return undefined
  return raw.map((entry) => {
    const call = (entry ?? {}) as { name?: unknown; arguments?: unknown; result?: unknown; status?: unknown }
    const name = String(call.name ?? 'tool')
    const denied = call.status === 'denied'
    const detail = denied
      ? '⛔ 权限不足（已拦截）'
      : JSON.stringify(call.arguments ?? call.result ?? {})
    return { name, detail }
  })
}

function CanvasEditor() {
  const location = useLocation()
  const { screenToFlowPosition, setCenter, setViewport, zoomTo } = useReactFlow()
  const [nodes, setNodes, onNodesChange] = useNodesState(defaultNodes())
  const [edges, setEdges, onEdgesChange] = useEdgesState(defaultEdges())
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [phase, setPhase] = useState<'idle' | 'running' | 'success' | 'failed'>('idle')
  const [round, setRound] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [note, setNote] = useState('正在从后端载入工作流…')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'load' | 'save' | 'run' | null>(null)
  const [flows, setFlows] = useState<WorkflowDto[]>([])
  const [wfId, setWfId] = useState<number | null>(null)
  const [wfName, setWfName] = useState('巡园浇水')
  const [runId, setRunId] = useState<number | null>(null)
  const [zoom, setZoom] = useState(0.85)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(readDrawerPref)
  const [menu, setMenu] = useState<{ id: string; x: number; y: number } | null>(null)
  const bodyEntry = useRef<string | null>(null)
  const armed = useRef(Boolean((location.state as { arm?: boolean } | null)?.arm))
  const followed = useRef('')
  const paneRef = useRef<HTMLDivElement>(null)
  const running = phase === 'running'

  /* 开关落本地：录屏时不想每次都手动拉开 */
  useEffect(() => {
    try {
      window.localStorage.setItem(DRAWER_KEY, drawerOpen ? '1' : '0')
    } catch {
      /* 隐私模式忽略 */
    }
  }, [drawerOpen])

  const selected = nodes.find((item) => item.id === selectedId) ?? null

  const loadWorkflow = useCallback(
    async (pickId?: number) => {
      setBusy('load')
      try {
        const list = await endpoints.workflows()
        if (!list.length) {
          setNote('后端还没有工作流，先用本地样例')
          return
        }
        const target =
          list.find((item) => item.id === pickId) ??
          list.find((item) => item.wf_key === 'patrol_irrigation') ??
          list[0]
        const view = fromDagJson(target.dag_json)
        setFlows(list)
        setWfId(target.id)
        setWfName(target.name)
        setNodes(view.nodes)
        setEdges(view.edges)
        setPhase('idle')
        setRunId(null)
        setRound(0)
        setElapsed(0)
        setNote(`已载入「${target.name}」v${target.version} · ${view.nodes.length} 个节点`)
        setError(null)
        // 画布重开要跟后端对账：上一轮没看完就翻页/重进，这里把真实状态接回来，
        // 避免出现「巡园早就结束了画布还在跳」或反过来「还在跑画布却装睡」。
        try {
          const latest = (await endpoints.runs(1, 1)).items[0]
          if (latest) {
            if (latest.status === 'running') {
              setRunId(latest.id)
              setPhase('running')
              setRound(1)
              setNote(`已接上后端正在执行 run #${latest.id} · 等待节点事件…`)
            } else if (latest.status !== 'success' || latest.finished_at) {
              const at = latest.finished_at ? latest.finished_at.slice(11, 19) : ''
              setNote(`已载入「${target.name}」 · 最近 run #${latest.id} 已结束（${latest.status}${at ? ` · ${at}` : ''}）`)
            }
          }
        } catch {
          /* 对账失败不影响画布可用 */
        }
      } catch (err) {
        setNote('后端未连通，画布用本地样例')
        setError(errText(err))
      } finally {
        setBusy(null)
      }
    },
    [setEdges, setNodes],
  )

  useEffect(() => {
    void loadWorkflow()
  }, [loadWorkflow])

  const save = useCallback(async () => {
    if (!wfId) {
      setNote('没有后端工作流 id，无法保存')
      return
    }
    const current = flows.find((item) => item.id === wfId)
    setBusy('save')
    try {
      const dag = toDagJson(nodes, edges, { wf_key: current?.wf_key, name: wfName })
      const updated = await endpoints.updateWorkflow(wfId, { name: wfName, dag_json: dag })
      setFlows((list) => list.map((item) => (item.id === updated.id ? updated : item)))
      setNote(`已保存到后端 · v${updated.version}`)
      setError(null)
    } catch (err) {
      setNote(`保存失败：${errText(err)}`)
      setError(errText(err))
    } finally {
      setBusy(null)
    }
  }, [edges, flows, nodes, wfId, wfName])

  const startRun = useCallback(async () => {
    if (!wfId) {
      setError('还没有载入后端工作流，无法运行')
      return
    }
    setBusy('run')
    setError(null)
    followed.current = ''
    setRound(0)
    setElapsed(0)
    setPhase('running')
    setNodes((current) =>
      current.map((item) => ({
        ...item,
        data: { ...item.data, status: 'idle', speech: undefined, calls: undefined, remain: undefined },
      })),
    )
    try {
      const result = await endpoints.runWorkflow(wfId)
      setRunId(result.run_id)
      setNote(result.run_id ? `已提交后端执行 · run #${result.run_id}` : '后端已受理，等待事件…')
    } catch (err) {
      setPhase('failed')
      setError(errText(err))
      setNote(`运行失败：${errText(err)}`)
    } finally {
      setBusy(null)
    }
  }, [setNodes, wfId])

  // 「开始巡园」确认后跳到本页：等工作流载入完再真正下发，
  // 这样 WS 订阅已经挂上，前几个节点的事件不会漏。
  useEffect(() => {
    if (!armed.current || !wfId || busy !== null) return
    armed.current = false
    void startRun()
  }, [busy, startRun, wfId])

  useEffect(() => {
    bodyEntry.current = resolveBodyEntry(nodes, edges)
  }, [edges, nodes])

  useEffect(() => {
    if (phase !== 'running') return
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [phase])

  // 画布执行事件：node_state 点亮/熄灭，run_status 收尾（contract 第 7 节）
  useEffect(() => {
    const offNode = dashboardSocket.on<NodeStateEventDto>('node_state', (data) => {
      if (!data?.node_id) return
      if (runId && data.run_id !== runId) return
      if (data.state === 'started') {
        // Self-Loop 一轮会把 body 整段重走（n9 → n10 → n11 都会再 started 一次），
        // 只有再次回到 body 入口才是新的一轮；按「节点重复」计会把 1 轮算成 3 轮。
        if (bodyEntry.current && data.node_id === bodyEntry.current) {
          setRound((value) => Math.max(1, value) + 1)
        }
        // 走到 loop 节点说明主链首验已经做完，至少是第 1 轮
        if (data.node_type === 'loop') setRound((value) => (value === 0 ? 1 : value))
      }
      setNodes((current) => applyNodeEvent(current, data))
    })
    const offRun = dashboardSocket.on<RunStatusEventDto>('run_status', (data) => {
      if (!data || typeof data.status !== 'string') return
      if (runId && data.run_id !== runId) return
      if (data.status === 'running') {
        setRunId(data.run_id)
        setPhase('running')
        setRound((value) => (value === 0 ? 1 : value))
        setNote(`执行中 · ${data.node_count ?? '?'} 个节点`)
        return
      }
      // 收尾兜底：没等到 finished 事件的节点（网络抖动/翻页回来）统一清算，
      // 不让画布上留着永远在跳的「执行中」光斑。
      const terminal: RunStatus = data.status === 'failed' ? 'failed' : 'done'
      setNodes((current) =>
        current.map((item) =>
          item.data.status === 'running'
            ? { ...item, data: { ...item.data, status: terminal, remain: undefined } }
            : item,
        ),
      )
      setPhase(data.status === 'success' ? 'success' : 'failed')
      if (typeof data.rounds === 'number' && data.rounds > 0) setRound(data.rounds)
      const seconds = typeof data.duration_ms === 'number' ? (data.duration_ms / 1000).toFixed(1) : '—'
      // needs_human 是正常收尾（转人工复核），不是「执行失败」，提示要分开写
      if (data.status === 'needs_human') {
        setNote(`执行完成 · ${seconds}s · 已转人工复核（湿度不达标或数据存疑）`)
      } else if (data.status === 'success') {
        setNote(`执行完成 · ${seconds}s · ${data.rounds ?? 1} 轮`)
      } else {
        setNote(`执行失败：${data.error || '未知原因'}`)
      }
    })
    return () => {
      offNode()
      offRun()
    }
  }, [runId, setNodes])

  // 让执行中的节点自动居中
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
    setNodes((current) =>
      current.map((item) => (item.id === selectedId ? { ...item, data: { ...item.data, ...patch } } : item)),
    )
    setNote('节点配置已改，点右上「保存」写回后端。')
  }

  const removeNode = (id: string) => {
    setNodes((current) => current.filter((item) => item.id !== id))
    setEdges((current) => current.filter((edge) => edge.source !== id && edge.target !== id))
    if (selectedId === id) setSelectedId(null)
    setMenu(null)
    setNote('已删除这个模块，点「保存」写回后端')
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
    setNote('已复制到旁边，点「保存」写回后端')
  }

  const shown = palette.filter((item) => {
    const word = query.trim()
    if (!word) return true
    return item.label.includes(word) || item.hint.includes(word)
  })

  return (
    <div className="relative flex h-full min-h-[640px] w-full min-w-0">
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
            {flows.length > 1 ? (
              <select
                aria-label="选择工作流"
                className="max-w-[240px] truncate rounded-btn border border-line bg-panel px-2 py-1 text-[20px] font-medium leading-[1.3] text-paper"
                value={wfId ?? ''}
                disabled={running}
                onChange={(event) => void loadWorkflow(Number(event.target.value))}
              >
                {flows.map((flow) => (
                  <option key={flow.id} value={flow.id}>
                    {flow.name}
                  </option>
                ))}
              </select>
            ) : (
              <p className="truncate text-[20px] font-medium leading-[1.3] text-paper">{wfName}</p>
            )}
            <p className={`mt-0.5 truncate text-xs leading-none ${error ? 'text-danger' : 'text-mute'}`} title={note}>
              {error ?? note}
            </p>
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
              aria-pressed={drawerOpen}
              title={drawerOpen ? '收起右侧运行对话' : '展开右侧运行对话：同屏看结构和发言'}
              className={`inline-flex h-9 items-center gap-1.5 rounded-btn px-3 text-xs leading-none shadow-[0_6px_20px_rgba(23,33,27,0.06)] ${
                drawerOpen ? 'bg-tea text-white hover:bg-teaHover' : 'bg-panel text-paper hover:text-tea'
              }`}
              onClick={() => setDrawerOpen((open) => !open)}
            >
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
                <rect x="1" y="2" width="12" height="10" rx="2" fill="none" stroke="currentColor" strokeWidth="1.2" />
                <path d="M8.5 2v10" stroke="currentColor" strokeWidth="1.2" />
              </svg>
              对话
            </button>
            <button
              type="button"
              disabled={busy !== null || running}
              className="h-11 rounded-btn bg-panel px-3 text-base text-dim shadow-[0_6px_20px_rgba(23,33,27,0.06)] disabled:opacity-50"
              onClick={() => void save()}
            >
              {busy === 'save' ? '保存中…' : '保存'}
            </button>
            <button
              type="button"
              disabled={busy !== null || running}
              className="h-11 rounded-btn bg-panel px-3 text-base text-dim shadow-[0_6px_20px_rgba(23,33,27,0.06)] disabled:opacity-50"
              onClick={() => {
                void loadWorkflow(wfId ?? undefined)
                setViewport({ x: 120, y: 16, zoom: 0.85 }, { duration: 280 })
              }}
            >
              从后端重载
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

        <div className="absolute bottom-4 left-1/2 z-30 flex -translate-x-1/2 items-center gap-1 whitespace-nowrap rounded-full border border-line bg-panel p-1.5 shadow-[0_10px_30px_rgba(23,33,27,0.1)]">
          <div className="flex items-center gap-0.5 rounded-full bg-panel2 p-1">
            <button
              type="button"
              title="缩小"
              aria-label="缩小"
              className="flex h-8 w-8 items-center justify-center rounded-full text-lg leading-none text-dim hover:bg-panel"
              onClick={() => zoomTo(Math.max(0.35, zoom - 0.1))}
            >
              −
            </button>
            <button
              type="button"
              title="恢复 100%"
              className="num h-8 min-w-[3.5rem] rounded-full px-2 text-sm text-paper hover:bg-panel"
              onClick={() => zoomTo(1)}
            >
              {Math.round(zoom * 100)}%
            </button>
            <button
              type="button"
              title="放大"
              aria-label="放大"
              className="flex h-8 w-8 items-center justify-center rounded-full text-lg leading-none text-dim hover:bg-panel"
              onClick={() => zoomTo(Math.min(1.4, zoom + 0.1))}
            >
              ＋
            </button>
          </div>
          <button
            type="button"
            aria-expanded={pickerOpen}
            className="h-10 shrink-0 whitespace-nowrap rounded-full bg-tea px-4 text-base text-white hover:bg-teaHover active:bg-teaPress"
            onClick={() => setPickerOpen((open) => !open)}
          >
            ＋ 添加节点
          </button>
          {running ? (
            <button
              type="button"
              className="h-10 shrink-0 whitespace-nowrap rounded-full bg-[#FFECE8] px-4 text-base text-danger"
              onClick={() => {
                setPhase('idle')
                setNote('已停止跟随动画；后端这一轮仍会跑完')
              }}
            >
              停止跟随
            </button>
          ) : (
            <button
              type="button"
              disabled={busy !== null || !wfId}
              className="h-10 shrink-0 whitespace-nowrap rounded-full bg-tea px-5 text-base text-white hover:bg-teaHover active:bg-teaPress disabled:opacity-50"
              onClick={() => void startRun()}
            >
              {busy === 'run' ? '下发中…' : '运行'}
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
      <RunChatDrawer
        open={drawerOpen}
        runId={runId}
        running={running}
        onClose={() => setDrawerOpen(false)}
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
            {node.data.calls.map((call, index) => (
              <li key={`${call.name}-${index}`} className="rounded-btn bg-ink px-3 py-2 text-sm leading-normal">
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
