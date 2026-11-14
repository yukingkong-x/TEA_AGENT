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
  PageDto,
  SensorHistoryDto,
  SensorLatestDto,
  SettingsDto,
  RunDetailDto,
  TaskDto,
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

  alerts: (params: { level?: string; page?: number; page_size?: number } = {}) =>
    api.get<PageDto<AlertDto>>(apiPath.alerts, params),

  ackAlert: (id: number) => api.post<AlertDto>(`${apiPath.alerts}/${id}/ack`),

  agents: () => api.get<AgentDto[]>(apiPath.agents),

  settings: () => api.get<SettingsDto>(apiPath.settings),

  /** 只提交用户真正改过的字段：GET 回来的值带掩码 sk-a****wxyz，原样回传会把掩码当明文落库 */
  updateSettings: (patch: Record<string, unknown>) => api.put<SettingsDto>(apiPath.settings, patch),

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

  verifyList: (params: { conclusion?: string; page?: number; page_size?: number } = {}) =>
    api.get<PageDto<Record<string, unknown>>>(apiPath.verify, params),

  verifyTask: (taskNo: string) => api.post<Record<string, unknown>>(`${apiPath.verify}/${encodeURIComponent(taskNo)}`, undefined, undefined, 30_000),

  reports: (params: { report_type?: string; page?: number; page_size?: number } = {}) =>
    api.get<PageDto<Record<string, unknown>>>(apiPath.reports, params),

  report: (id: number) => api.get<Record<string, unknown>>(`${apiPath.reports}/${id}`),

  generateReport: (runId: number) =>
    api.post<{ report_id: number }>(apiPath.reportsGenerate, undefined, { run_id: runId }, 30_000),
}

/** 后端 `_parse_dt` 认 `%Y-%m-%d %H:%M:%S` 也认带 T 的；这里给本地时区、不带 Z */
function isoLocal(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  )
}
