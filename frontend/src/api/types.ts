/**
 * 后端 DTO 类型 —— 逐字对齐 `backend/app/api/*.py` 里的 `to_dict()`。
 * 改这里之前先去核后端代码，别凭记忆写字段名。
 */

export type RunMode = 'mock' | 'real'

export type DeviceState = 'online' | 'suspect' | 'offline'

/** GET /api/devices */
export type DeviceDto = {
  device_id: string
  name: string
  role: 'field' | 'soil' | 'actuator' | string
  location: string | null
  is_mock: boolean
  online: boolean
  last_seen: string | null
  state: DeviceState
}

/** GET /api/sensor/latest —— 每台设备一个对象 */
export type SensorLatestDto = {
  device_id: string
  name: string
  role: string
  is_mock: boolean
  online: boolean
  metrics: Record<string, number>
  ts: string | null
}

/** GET /api/sensor/history */
export type SensorHistoryDto = {
  device_id: string
  metric: string
  from: string
  to: string
  count: number
  points: { ts: string; value: number }[]
}

/** 后端 tasks.status 9 态（PRD 6.6 第 397 行） */
export type TaskStatusDto =
  | 'pending'
  | 'dispatched'
  | 'running'
  | 'success'
  | 'failed'
  | 'timeout'
  | 'retrying'
  | 'dead'
  | 'canceled'

/** 后端 tasks.type（PRD 6.6） */
export type TaskTypeDto = 'agent_call' | 'device_cmd' | 'verify' | 'report' | 'selfloop'

/** GET /api/tasks 单行 */
export type TaskDto = {
  id: number
  task_no: string
  run_id: number | null
  type: TaskTypeDto | string
  payload: Record<string, unknown> | null
  priority: number
  score: number | null
  status: TaskStatusDto
  assigned_agent: string | null
  assigned_device: string | null
  retry_count: number
  timeout_s: number | null
  deadline_at: string | null
  result: Record<string, unknown> | null
  created_at: string | null
  updated_at: string | null
}

/** 统一分页封装（backend/app/api/_common.py） */
export type PageDto<T> = {
  items: T[]
  total: number
  page: number
  page_size: number
  pages: number
}

/** GET /api/alerts 单行 */
export type AlertDto = {
  id: number
  level: 'info' | 'warning' | 'critical' | string
  source: string
  message: string
  acknowledged: boolean
  created_at: string | null
}

/** GET /api/agents 单行 */
export type AgentDto = {
  id: number
  agent_key: string
  name: string
  avatar: string | null
  system_prompt: string | null
  tools_json: string[]
  model: string | null
  temperature: number | null
  enabled: boolean
  updated_at: string | null
}

/** GET /api/settings */
export type SettingsDto = {
  mode: RunMode
  llm_ready: boolean
  items: { key: string; value: unknown; description?: string; masked?: boolean }[]
}

/** GET /api/health */
export type HealthDto = {
  status: 'ok' | 'degraded'
  db: 'up' | 'down'
  redis: 'up' | 'down'
  mqtt: 'up' | 'down'
  mode: RunMode
  simulator: boolean
  ws_clients: number
  llm_ready: boolean
  seams: Record<string, 'ready' | 'not_ready'>
  version: string
  ts: string
}

/** GET /api/workflows —— dag_json 里的节点用 next / branches / body_next 显式引用（蛇形） */
export type WorkflowDto = {
  id: number
  wf_key: string
  name: string
  version: number
  enabled: boolean
  dag_json: DagJson
  updated_at: string | null
}

/** GET /api/runs */
export type WorkflowRunDto = {
  id: number
  wf_id: number
  status: string
  trigger: string
  context: Record<string, unknown> | null
  started_at: string | null
  finished_at: string | null
  created_at: string | null
}

/** 后端 dag_json（`backend/app/workflow/dag.py` 校验的就是这个结构） */
export type DagNode = {
  id: string
  type: 'start' | 'agent' | 'tool' | 'condition' | 'parallel' | 'loop' | 'end' | string
  name?: string
  agent_key?: string
  tool?: string
  params?: Record<string, unknown>
  input?: string
  next?: string | string[] | null
  branches?: Record<string, string | string[]> | string[]
  body_next?: string | null
  expression?: string
  exit_expression?: string
  max_iterations?: number
  position?: { x: number; y: number }
}

export type DagJson = {
  wf_key?: string
  name?: string
  nodes: DagNode[]
  edges?: unknown[]
  meta?: Record<string, unknown>
}

/** WS /ws/dashboard 统一信封 */
export type DashMessage<T = Record<string, unknown>> = {
  type:
    | 'telemetry'
    | 'device_status'
    | 'task_status'
    | 'agent_message'
    | 'node_state'
    | 'run_status'
    | 'alert'
    | 'mode_changed'
    | 'run_started'
    | 'node_started'
    | 'node_finished'
    | 'run_finished'
    | 'pong'
    | string
  data: T
  ts: number
}
