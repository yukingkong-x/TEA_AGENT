export type DeviceStatus = 'online' | 'suspect' | 'offline' | 'alarm'

export type Device = {
  id: string
  name: string
  role: string
  status: DeviceStatus
  place: string
  reading: string
  detail: { label: string; value: string }[]
  seriesName: string
  unit: string
  series: number[]
  /** 主指标的 metric key（temperature_c / soil_moisture / pump_seconds），拉历史曲线要用 */
  metric?: string
  /** 后端 is_mock：Mock 设备 id 带前缀，展示上要区分 */
  isMock?: boolean
  x: number
  y: number
}

export const devices: Device[] = [
  {
    id: 'k10-field-01',
    name: '巡园员一号',
    role: '环境',
    status: 'online',
    place: 'A区茶垄',
    reading: '24.6℃',
    detail: [
      { label: '气温', value: '24.6℃' },
      { label: '空气湿度', value: '63.2%' },
      { label: '光照', value: '1250 lx' },
    ],
    seriesName: '气温',
    unit: '℃',
    series: [22.4, 22.1, 21.8, 21.6, 21.9, 22.6, 23.4, 24.1, 24.8, 25.2, 25.0, 24.6],
    x: 24,
    y: 52,
  },
  {
    id: 'esp32-soil-02',
    name: '土壤墒情',
    role: '土壤',
    status: 'online',
    place: 'A区茶垄',
    reading: '38.5%',
    detail: [
      { label: '土壤湿度', value: '38.5%' },
      { label: '原始值', value: '2870' },
      { label: '缺水线', value: '40%' },
    ],
    seriesName: '土壤湿度',
    unit: '%',
    series: [46.8, 46.1, 45.2, 44.5, 43.6, 42.8, 42.0, 41.2, 40.5, 39.8, 39.2, 38.5],
    x: 50,
    y: 68,
  },
  {
    id: 'k10-act-03',
    name: '执行终端',
    role: '浇水',
    status: 'online',
    place: 'A区茶垄',
    reading: '待命',
    detail: [
      { label: '状态', value: '待命' },
      { label: '最近浇水', value: '无' },
      { label: '单次上限', value: '120 秒' },
    ],
    seriesName: '浇水秒数',
    unit: '秒',
    series: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    x: 74,
    y: 50,
  },
]

export const soilDay = [
  46.8, 46.4, 46.1, 45.7, 45.2, 44.8, 44.5, 44.0, 43.6, 43.1, 42.8, 42.4, 42.0, 41.6, 41.2, 40.8,
  40.5, 40.1, 39.8, 39.5, 39.2, 39.0, 38.8, 38.6, 38.5,
]

export const metrics = [
  { id: 'online', label: '在线设备', value: 3, suffix: '', hint: '三块板都有心跳' },
  { id: 'tasks', label: '今日任务', value: 9, suffix: '', hint: '打开任务中心查看' },
  { id: 'loop', label: '闭环成功率', value: 100, suffix: '%', hint: '模拟巡园已闭环' },
  { id: 'rate', label: '平均达成率', value: 100, suffix: '%', hint: '第 2 轮 100.00%' },
] as const

export const agents = [
  { key: 'scout', name: '巡园管家', avatar: '🍃', job: '汇总读数，发出预警' },
  { key: 'weather', name: '气象员', avatar: '☁️', job: '看未来 12 小时天气' },
  { key: 'soil', name: '土壤师', avatar: '🌱', job: '给墒情评级' },
  { key: 'pest', name: '植保员', avatar: '🐞', job: '对照知识库查风险' },
  { key: 'decision', name: '灌溉决策官', avatar: '💧', job: '决定浇不浇' },
  { key: 'executor', name: '执行管家', avatar: '🔧', job: '唯一可以下水泵' },
  { key: 'verifier', name: '验证审计官', avatar: '📋', job: '用复测计算达成率' },
]

