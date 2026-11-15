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

/**
 * 后端 tasks.status：`models/tasks.py` 枚举 9 态 + needs_human
 * （needs_human 在枚举补齐前会以 failed + result.verdict 出现）。
 * 没有 queued / completed / waiting_tool / tool_done。
 */
export type TaskStatusDto =
  | 'pending'
  | 'dispatched'
  | 'running'
  | 'success'
  | 'failed'
  | 'timeout'
  | 'retrying'
  | 'dead'
  | 'needs_human'
  | 'canceled'

/** 后端 tasks.type（PRD 6.6） */
export type TaskTypeDto = 'agent_call' | 'device_cmd' | 'verify' | 'report' | 'selfloop'

export type TaskResultDto = {
  /** 熔断拒绝：breaker_open */
  rejected?: string
  retry_after_s?: number
  /** 验证结论：success / failed / needs_human */
  verdict?: string
  [key: string]: unknown
}

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
  result: TaskResultDto | null
  created_at: string | null
  updated_at: string | null
}

/**
 * WS `task_status`（contract 第 9 节）：调度器每次改状态推一条。
 * 轨迹直接画 `from → to`，前端不自己推状态机。
 */
export type TaskStatusEventDto = {
  task_no: string
  run_id?: number | null
  from: TaskStatusDto | null
  to: TaskStatusDto
  reason?: string
  retry_count?: number
  score?: number | null
  assigned_agent?: string | null
  assigned_device?: string | null
  result?: TaskResultDto | null
  ts?: string | number
}

/**
 * 验证结果（contract 第 10 节）—— 量纲钉死，别混：
 * achievement / gap / confidence 是 **0-100**；confidence_detail.* 是 **0-1** 原始分。
 */
export type VerificationDto = {
  task_no: string
  verification_id: number
  verdict: 'success' | 'failed' | 'needs_human'
  /** 0-100（%） */
  achievement: number
  /** 0-100（%） */
  gap: number
  over_irrigated: boolean
  /** 0-100，60 为转人工阈值 */
  confidence: number
  measured: number
  /** 可能为 null（没有基线）：显示「—」，不要 ?? 0 */
  baseline: number | null
  /**
   * 基线缺失（contract 第 10 节）：true 时 achievement 是「算不出来」，不是 0%。
   * 圆环按灰/空态画，别画成绿色的 0%。
   */
  baseline_missing?: boolean
  /** 哪个传感器给的基线，可能为 null */
  sensor_id?: string | null
  round_no: number
  /** 三路原始分，0-1，权重 0.5 / 0.3 / 0.2 */
  confidence_detail: {
    data_quality: number
    rule_cross: number
    consistency: number
    reasons?: string[]
  }
  correction: { strategy: string; duration_s: number; times: number; interval_s: number } | null
  note?: string
}

/** 知识库命中（contract 第 8 节）：score 0-1 原样显示，空数组 = 未检索到 */
export type KnowledgeHitDto = {
  title: string
  chunk_text: string
  score: number
  doc_id: number
  chunk_index: number
}

/** POST /api/knowledge/search —— 后端包了一层，hits 才是命中数组 */
export type KnowledgeSearchDto = {
  question: string
  top_k: number
  hits: KnowledgeHitDto[]
}

/** GET /api/verify —— 验证记录（报告页圆环、指标卡聚合的数据源） */
export type VerificationRecordDto = {
  id: number
  run_id: number | null
  task_no: string
  /** 基线，可能为 null */
  baseline_value: number | null
  target_low: number | null
  target_high: number | null
  measured_value: number | null
  /** 0-100 */
  achievement: number | null
  /** 0-100 */
  confidence: number | null
  /** 三路原始分，0-1 */
  conf_detail: {
    data_quality?: number
    rule_cross?: number
    consistency?: number
    reasons?: string[]
  } | null
  /** success / failed / needs_human */
  conclusion: string
  created_at: string | null
}

/** GET/POST/DELETE /api/devices/mock、/fault、/weather —— 都是同一份模拟器状态 */
export type MockStateDto = {
  mode?: RunMode
  running?: boolean
  devices?: string[]
  weather?: 'sunny' | 'cloudy' | 'rainy' | 'frost' | string
  soil_moisture?: number
  /** offline 是 {device_id: 剩余秒}，其余是布尔/截止时间 */
  faults?: {
    offline?: Record<string, number>
    ack_timeout_until?: number
    dry_soil?: boolean
    stuck_moisture?: boolean
    sensor_jitter?: boolean
  }
}

/** PRD 12.2 五种故障 */
export type FaultName = 'offline' | 'ack_timeout' | 'dry_soil' | 'stuck_moisture' | 'sensor_jitter'

/**
 * GET /api/tasks/{task_no}/events —— 轨迹全量回放（队长 11.14 上线）。
 * 抽屉先拉这个，再用 WS `task_status` 增量 append，按 id 去重。
 * `at` 带 T，Safari 能解。
 * `event="verify"` 是验证那一跳：from=任务原状态、to=结论、reason=verdict，payload 里有
 * verification_id / achievement / confidence / note —— 单独画一条虚线。
 */
export type TaskEventDto = {
  id: number
  event: 'task_status' | 'verify' | string
  from: TaskStatusDto | null
  to: TaskStatusDto | string
  reason: string | null
  actor: string | null
  at: string
  payload?: Record<string, unknown> | null
}

/** 画布执行事件（contract 第 7 节）：`run_status` + `node_state` 两类，用 state 区分开始/结束 */
export type RunStatusEventDto = {
  run_id: number
  status: 'running' | 'success' | 'failed'
  wf_key?: string
  trigger?: string
  node_count?: number
  rounds?: number
  duration_ms?: number
  error?: string
}

export type NodeStateEventDto = {
  run_id: number
  node_id: string
  node_type: string
  name?: string
  agent_key?: string
  /** 只在事件上有：started / finished */
  state: 'started' | 'finished'
  /** 只在 finished 上有：running / done / failed / skipped */
  status?: 'running' | 'done' | 'failed' | 'skipped' | string
  output?: string
  error?: string
  degraded?: boolean
  duration_ms?: number
  tool_calls?: unknown
  tokens_in?: number
  tokens_out?: number
}

/** GET /api/knowledge —— 文档列表（后端返回裸数组，不分页） */
export type KnowledgeDocDto = {
  id: number
  title: string
  source?: string | null
  status: string
  chunk_count?: number | null
  created_at: string | null
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

/** GET /api/runs/{run_id} 里的 agent_messages */
export type AgentMessageDto = {
  id: number
  run_id?: number | null
  agent_key: string
  role: 'user' | 'assistant' | 'tool' | 'system' | string
  content: string
  /** [{id, name, arguments, status, result}]，权限拒绝是 status: "denied" */
  tool_calls?: unknown
  /** 知识库命中数组，空数组 = 未检索到（正常结果） */
  citations?: KnowledgeHitDto[] | unknown
  tokens_in?: number | null
  tokens_out?: number | null
  latency_ms?: number | null
  created_at: string | null
}

/** GET /api/runs/{run_id} */
export type RunDetailDto = {
  run: WorkflowRunDto
  tasks: TaskDto[]
  messages: AgentMessageDto[]
  /** 节点耗时明细；历史 run 没有这张表的数据时是空数组（不是 404） */
  nodes?: NodeRecordDto[]
  node_summary?: NodeSummaryDto | null
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

/** GET /api/runs/{id}/nodes —— 引擎落库的节点耗时（B 的 workflow_node_records） */
export type NodeRecordDto = {
  node_id: string
  node_type: string
  name: string
  status: string
  /** 第几轮；主链首验是 1，Self-Loop 回跳的节点是 2 */
  round_no: number
  duration_ms: number
  degraded: boolean
  tokens_in: number
  tokens_out: number
  tool_calls: { name?: string; status?: string }[]
  error?: string | null
}

export type NodeSummaryDto = {
  node_count: number
  duration_ms: number
  slowest: { node_id: string; name: string; duration_ms: number } | null
  /** Self-Loop 聚合耗时（包住 修正→执行→渗透→复验），别当单节点比 */
  loop: { node_id: string; name: string; duration_ms: number } | null
  degraded_count: number
  failed_count: number
}

/** GET /api/runs/{id}/rounds —— 与报告 Markdown 同源的轮次视图 */
export type RunRoundDto = {
  round_no: number
  /** 可能为 null（基线缺失）*/
  baseline: number | null
  measured: number
  /** 0-100 */
  achievement: number
  /** 0-1（注意：验证记录接口是 0-100，这里是 0-1，适配层统一 ×100） */
  confidence: number
  verdict: string
  target_low: number
  target_high: number
  /** 本轮浇水时长（秒），来自任务载荷；0/缺省 = 没记录 */
  duration_s: number
  /** 诊断文案（feedback_logs 的 failure_reason） */
  note: string
  conf_detail: VerificationRecordDto['conf_detail']
}

export type RunRoundsDto = {
  run_id: number
  wf_name: string
  trigger: string
  started_at: string
  finished_at: string
  /** success / failed / needs_human / unverified / running / pending */
  outcome: string
  rounds: RunRoundDto[]
  timeline: { ts: string; name: string; event: string; status: string; duration_ms: number }[]
  alerts: { level: string; message: string; source: string }[]
  confidence_reasons: string[]
  achievement_detail: {
    target_low: number
    target_high: number
    over_irrigated: boolean
    baseline_in_range: boolean
  }
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
