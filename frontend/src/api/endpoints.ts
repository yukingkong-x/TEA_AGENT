/**
 * 全部 REST 端点，逐条对应 `backend/app/api/*.py`。
 * 页面只 import 这里的函数，不拼 URL、不碰 query 字符串。
 */
import { api } from './client'
import type {
  AgentDto,
  AlertDto,
  DeviceDto,
  HealthDto,
  KnowledgeDocDto,
  KnowledgeSearchDto,
  MockStateDto,
  PageDto,
  SensorHistoryDto,
  SensorLatestDto,
  SettingsDto,
  RunDetailDto,
  TaskDto,
  TaskEventDto,
  VerificationRecordDto,
  WorkflowDto,
  WorkflowRunDto,
} from './types'

const apiPath = {
  health: '/health',
  devices: '/devices',
  sensorLatest: '/sensor/latest',
  sensorHistory: '/sensor/history',
  tasks: '/tasks',
  alerts: '/alerts',
  agents: '/agents',
  settings: '/settings',
  settingsMode: '/settings/mode',
  workflows: '/workflows',
  runs: '/runs',
  verify: '/verify',
  reports: '/reports',
  reportsGenerate: '/reports/generate',
  knowledge: '/knowledge',
  knowledgeUpload: '/knowledge/upload',
  knowledgeSearch: '/knowledge/search',
}

export const endpoints = {
  health: () => api.get<HealthDto>(apiPath.health),

  /** 缺省全量（Mock + 真机），按 is_mock 自己分组 */
  devices: (isMock?: boolean) =>
    api.get<DeviceDto[]>(apiPath.devices, { is_mock: isMock === undefined ? undefined : isMock }),

  sensorLatest: () => api.get<SensorLatestDto[]>(apiPath.sensorLatest),

  sensorHistory: (deviceId: string, metric: string, hours = 24, limit = 500) =>
    api.get<SensorHistoryDto>(apiPath.sensorHistory, {
      device_id: deviceId,
      metric,
      from: isoLocal(new Date(Date.now() - hours * 3600_000)),
      to: isoLocal(new Date()),
      limit,
    }),

  tasks: (params: { status?: string; type?: string; page?: number; page_size?: number } = {}) =>
    api.get<PageDto<TaskDto>>(apiPath.tasks, params),

  task: (taskNo: string) => api.get<TaskDto>(`${apiPath.tasks}/${encodeURIComponent(taskNo)}`),

  /** 轨迹全量回放（抽屉打开时拉一次），随后用 WS task_status 增量 append 并按 id 去重 */
  taskEvents: (taskNo: string) =>
    api.get<PageDto<TaskEventDto>>(`${apiPath.tasks}/${encodeURIComponent(taskNo)}/events`, {
      page: 1,
      page_size: 200,
    }),

  alerts: (params: { level?: string; page?: number; page_size?: number } = {}) =>
    api.get<PageDto<AlertDto>>(apiPath.alerts, params),

  ackAlert: (id: number) => api.post<AlertDto>(`${apiPath.alerts}/${id}/ack`),

  agents: () => api.get<AgentDto[]>(apiPath.agents),

  /** 改提示词 / 开关即时生效（patch 语义，只传要改的字段） */
  updateAgent: (agentKey: string, patch: Partial<Pick<AgentDto, 'name' | 'avatar' | 'system_prompt' | 'tools_json' | 'model' | 'temperature' | 'enabled'>>) =>
    api.put<AgentDto>(`${apiPath.agents}/${encodeURIComponent(agentKey)}`, patch),

  settings: () => api.get<SettingsDto>(apiPath.settings),

  /**
   * 后端 `SettingsIn` 是 `{ values: {...} }`，**不是平铺 patch**，直接传平铺会 422。
   * 只提交用户真正改过的字段：GET 回来的密钥是掩码 sk-a****wxyz，
   * 原样回传会把掩码当明文落库（后端只在 value 为空串时才跳过）。
   */
  updateSettings: (values: Record<string, unknown>) => api.put<SettingsDto>(apiPath.settings, { values }),

  setMode: (mode: 'mock' | 'real') => api.post<SettingsDto>(apiPath.settingsMode, undefined, { mode }),

  workflows: () => api.get<WorkflowDto[]>(apiPath.workflows),

  workflow: (id: number) => api.get<WorkflowDto>(`${apiPath.workflows}/${id}`),

  createWorkflow: (body: { wf_key: string; name: string; dag_json: WorkflowDto['dag_json']; enabled?: boolean }) =>
    api.post<WorkflowDto>(apiPath.workflows, body),

  updateWorkflow: (id: number, body: { name?: string; dag_json?: WorkflowDto['dag_json']; enabled?: boolean }) =>
    api.put<WorkflowDto>(`${apiPath.workflows}/${id}`, body),

  deleteWorkflow: (id: number) => api.del<{ deleted: number }>(`${apiPath.workflows}/${id}`),

  /** 依赖队长引擎；未接线时 503 SEAM_NOT_READY */
  runWorkflow: (id: number, trigger = 'manual') =>
    api.post<{ run_id: number | null; wf_id: number; trigger: string }>(
      `${apiPath.workflows}/${id}/run`,
      undefined,
      { trigger },
      30_000,
    ),

  runs: (page = 1, pageSize = 20) => api.get<PageDto<WorkflowRunDto>>(apiPath.runs, { page, page_size: pageSize }),

  /** 执行详情：run + tasks + messages（对话剧场的数据源） */
  run: (id: number) => api.get<RunDetailDto>(`${apiPath.runs}/${id}`),

  verifyList: (params: { task_no?: string; conclusion?: string; page?: number; page_size?: number } = {}) =>
    api.get<PageDto<VerificationRecordDto>>(apiPath.verify, params),

  /** 对某任务执行验证；渗透期没走完后端会拒/给低置信度，前端按钮要置灰等 90s */
  verifyTask: (taskNo: string) =>
    api.post<{ task_no: string; result: Record<string, unknown> }>(
      `${apiPath.verify}/${encodeURIComponent(taskNo)}`,
      undefined,
      undefined,
      90_000,
    ),

  reports: (params: { report_type?: string; page?: number; page_size?: number } = {}) =>
    api.get<PageDto<Record<string, unknown>>>(apiPath.reports, params),

  report: (id: number) => api.get<Record<string, unknown>>(`${apiPath.reports}/${id}`),

  generateReport: (runId: number) =>
    api.post<{ report_id: number }>(apiPath.reportsGenerate, undefined, { run_id: runId }, 30_000),

  /* ---------- 设置页：设备调试 / 故障注入 / 知识库 ---------- */

  /** 手动下发指令（设置页调试器）；返回 ack 或 accepted */
  deviceCmd: (deviceId: string, body: { action: string; params?: Record<string, unknown> }) =>
    api.post<Record<string, unknown>>(`${apiPath.devices}/${encodeURIComponent(deviceId)}/cmd`, body, undefined, 35_000),

  mockState: () => api.get<MockStateDto>(`${apiPath.devices}/mock`),

  startMock: () => api.post<MockStateDto>(`${apiPath.devices}/mock/start`),

  stopMock: () => api.post<MockStateDto>(`${apiPath.devices}/mock/stop`),

  /**
   * PRD 12.2 五种故障：offline / ack_timeout / dry_soil / stuck_moisture / sensor_jitter
   * 后端字段名是 `device`（不是 device_id），offline 才用它指定目标设备，默认土壤节点。
   */
  injectFault: (body: { fault: string; device?: string; seconds?: number }) =>
    api.post<MockStateDto>(`${apiPath.devices}/fault`, body),

  clearFault: (fault?: string) =>
    api.del<MockStateDto>(`${apiPath.devices}/fault`, fault ? { fault } : undefined),

  /** 档位是 query 参数（`?scenario=sunny`），不是 body */
  weather: (scenario: 'sunny' | 'cloudy' | 'rainy' | 'frost') =>
    api.post<MockStateDto>(`${apiPath.devices}/weather`, undefined, { scenario }),

  /** 后端返回裸数组，不分页 */
  knowledgeDocs: () => api.get<KnowledgeDocDto[]>(apiPath.knowledge),

  uploadKnowledge: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.upload<KnowledgeDocDto>(apiPath.knowledgeUpload, form)
  },

  deleteKnowledge: (id: number) => api.del<{ deleted: number }>(`${apiPath.knowledge}/${id}`),

  /** 返回 `{question, top_k, hits}`；hits 为空数组 = 未检索到，是正常结果 */
  searchKnowledge: (question: string, topK = 3) =>
    api.post<KnowledgeSearchDto>(apiPath.knowledgeSearch, { question, top_k: topK }, undefined, 20_000),
}

/** 后端 `_parse_dt` 认 `%Y-%m-%d %H:%M:%S` 也认带 T 的；这里给本地时区、不带 Z */
function isoLocal(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}
