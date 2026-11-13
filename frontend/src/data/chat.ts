export type ToolCall = {
  name: string
  args: Record<string, unknown>
  result: Record<string, unknown>
}

export type Citation = {
  id: string
  excerpt: string
}

export type ChatMessage = {
  id: string
  at: string
  agentKey: string
  content: string
  degraded?: boolean
  calls?: ToolCall[]
  citations?: Citation[]
}

const teaNote: Citation = {
  id: '1',
  excerpt: '春茶期土壤湿度宜保持在 55%–65%。低于 40% 属于缺水，补灌与植保无冲突。',
}

export const chatThreads: Record<string, ChatMessage[]> = {
  'run-1001': [
    {
      id: 'm1',
      at: '21:06:12',
      agentKey: 'scout',
      content:
        '【巡园播报】A区茶垄：气温 24.6℃，空气湿度 63.2%，光照 1250 lx，土壤湿度 38.5%。预警：土壤湿度低于 40%。请气象员、土壤师、植保员评估是否有作业需求。',
      calls: [
        {
          name: 'get_env_status',
          args: { device_id: 'k10-field-01' },
          result: { temp_c: 24.6, humidity: 63.2, lux: 1250 },
        },
        {
          name: 'get_soil_status',
          args: { device_id: 'esp32-soil-02' },
          result: { moisture: 38.5, trend: '下降' },
        },
        {
          name: 'raise_alert',
          args: { level: 'warning', message: '土壤湿度低于 40%' },
          result: { status: 'sent' },
        },
      ],
    },
    {
      id: 'm2',
      at: '21:06:18',
      agentKey: 'weather',
      content: '【气象评估】未来 12 小时天气数据不可用。结论：数据不可用。',
      degraded: true,
      calls: [
        {
          name: 'get_weather',
          args: { zone: 'A区' },
          result: { status: 'unavailable' },
        },
      ],
    },
    {
      id: 'm3',
      at: '21:06:20',
      agentKey: 'soil',
      content: '【墒情报告】A区土壤湿度 38.5%，趋势下降，评级：轻度缺水。建议：建议灌溉，目标湿度区间 55%-65%。',
      calls: [
        {
          name: 'get_soil_status',
          args: { device_id: 'esp32-soil-02' },
          result: { moisture: 38.5, level: '轻度缺水' },
        },
      ],
    },
    {
      id: 'm4',
      at: '21:06:22',
      agentKey: 'pest',
      content: '【植保核查】知识库检索到 1 条相关条目 [1]。风险：无。建议：无冲突。',
      citations: [teaNote],
      calls: [
        {
          name: 'query_knowledge',
          args: { question: 'A区土壤湿度 38.5%，计划灌溉' },
          result: { hits: 1, ids: ['doc-1#1'] },
        },
      ],
    },
    {
      id: 'm5',
      at: '21:06:31',
      agentKey: 'decision',
      content: '【决策】本轮决策：irrigate。方案：对 A区执行浇水 30 秒，目标湿度 55-65%，优先级 6。依据：土壤师评为轻度缺水，气象评估为数据不可用。',
      calls: [
        {
          name: 'send_device_cmd',
          args: { device_id: 'k10-act-03', action: 'pump', params: { duration_s: 30 } },
          result: { status: 'denied', reason: 'permission' },
        },
        {
          name: 'create_task',
          args: { device_id: 'k10-act-03', action: 'pump', duration_s: 30, priority: 6, baseline: 38.5 },
          result: { task_no: 'task-1101', status: 'pending' },
        },
      ],
    },
    {
      id: 'm6',
      at: '21:06:40',
      agentKey: 'executor',
      content: '【执行反馈】任务 task-1101：已下发，设备已接收，执行中。设备状态：在线。',
      calls: [
        {
          name: 'send_device_cmd',
          args: { device_id: 'k10-act-03', action: 'pump', params: { duration_s: 30 } },
          result: { status: 'received', ack: 'running' },
        },
      ],
    },
    {
      id: 'm7',
      at: '21:08:20',
      agentKey: 'verifier',
      content: '【验证报告】第 1 轮：基线 38.5% → 复测 45.0%，目标 [55,65]，达成率 39.39%，置信度 100.00%。结论：未达标，补灌 20 秒后再验。',
      calls: [
        {
          name: 'get_soil_status',
          args: { device_id: 'esp32-soil-02', samples: 3 },
          result: { median: 45.0, achievement: 39.39, confidence: 100 },
        },
      ],
    },
    {
      id: 'm8',
      at: '21:08:48',
      agentKey: 'executor',
      content: '【执行反馈】任务 task-1102：补灌 20 秒已下发，设备已完成。',
      calls: [
        {
          name: 'send_device_cmd',
          args: { device_id: 'k10-act-03', action: 'pump', params: { duration_s: 20 } },
          result: { status: 'done', task_no: 'task-1102' },
        },
      ],
    },
    {
      id: 'm9',
      at: '21:10:30',
      agentKey: 'verifier',
      content: '【验证报告】第 2 轮：基线 45.0% → 复测 57.0%，目标 [55,65]，达成率 100.00%，置信度 100.00%。结论：闭环成功。',
      calls: [
        {
          name: 'get_soil_status',
          args: { device_id: 'esp32-soil-02', samples: 3 },
          result: { median: 57.0, achievement: 100, confidence: 100 },
        },
      ],
    },
  ],
  'run-1002': [
    {
      id: 'j1',
      at: '21:20:06',
      agentKey: 'scout',
      content: '【巡园播报】A区茶垄土壤湿度读数抖动，连续三次为 31.2%、45.0%、52.8%。',
      calls: [
        {
          name: 'get_soil_status',
          args: { device_id: 'esp32-soil-02', samples: 3 },
          result: { values: [31.2, 45.0, 52.8], range: 21.6 },
        },
      ],
    },
    {
      id: 'j2',
      at: '21:22:10',
      agentKey: 'verifier',
      content: '【验证报告】基线 38.5% → 复测 45.0%，达成率 39.39%，置信度 50.00%。置信度低于 60%，转人工，本轮挂起。',
    },
  ],
}
