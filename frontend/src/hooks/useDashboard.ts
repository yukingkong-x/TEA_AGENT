/**
 * 总控页数据源：REST 首屏 + WS 增量，任何一步失败都退回 `src/data/snapshot.ts` 的假数据，
 * 页面永远有东西可看（彩排时后端没起也不会白屏）。
 *
 * 三个必须记住的后端事实（队友B 特意强调过）：
 * 1. 设备字段是 `device_id / role / location / state`，不是 id / role中文 / place / status；
 * 2. Mock 模式下设备 id 带前缀（`mock-k10-field-01`），**绝不能按 id 硬编码定位**，只能按 role；
 * 3. `/api/sensor/latest` 只给最新一条，曲线得自己按时间戳攒。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { endpoints } from '../api/endpoints'
import { dashboardSocket } from '../api/socket'
import type { DeviceDto, SensorLatestDto } from '../api/types'
import { devices as fallbackDevices, metrics as fallbackMetrics, soilDay, type Device, type DeviceStatus } from '../data/snapshot'

type Metric = { id: string; label: string; value: number; suffix: string; hint: string }

/** 后端 role → 中文名（只做展示，逻辑一律用 role） */
const ROLE_LABEL: Record<string, string> = {
  field: '环境',
  soil: '土壤',
  actuator: '浇水',
}

/** 地图上的固定摆位：后端不存坐标，按 role 落点比按 id 猜稳 */
const ROLE_SPOT: Record<string, { x: number; y: number }> = {
  field: { x: 24, y: 52 },
  soil: { x: 50, y: 68 },
  actuator: { x: 74, y: 50 },
}

const ROLE_PRIMARY: Record<string, { metric: string; unit: string; label: string }> = {
  field: { metric: 'temperature_c', unit: '℃', label: '气温' },
  soil: { metric: 'soil_moisture', unit: '%', label: '土壤湿度' },
  actuator: { metric: 'pump_seconds', unit: '秒', label: '浇水秒数' },
}

const METRIC_LABEL: Record<string, { label: string; unit: string }> = {
  temperature_c: { label: '气温', unit: '℃' },
  humidity_air: { label: '空气湿度', unit: '%' },
  lux: { label: '光照', unit: ' lx' },
  soil_moisture: { label: '土壤湿度', unit: '%' },
  soil_raw: { label: '原始值', unit: '' },
  pump_seconds: { label: '浇水秒数', unit: ' 秒' },
  rssi: { label: '信号', unit: ' dBm' },
}

const fmt = (value: number | undefined, unit: string) =>
  value === undefined || Number.isNaN(value) ? '—' : `${value.toFixed(1)}${unit}`

function stateOf(dto: DeviceDto): DeviceStatus {
  if (dto.online === false || dto.state === 'offline') return 'offline'
  if (dto.state === 'suspect') return 'suspect'
  return 'online'
}

/** 后端 DTO + 最新读数 → 地图/抽屉要的视图模型 */
function toView(dto: DeviceDto, latest: SensorLatestDto | undefined): Device {
  const role = String(dto.role || 'field')
  const primary = ROLE_PRIMARY[role] ?? ROLE_PRIMARY.field
  const metrics = latest?.metrics ?? {}
  const value = metrics[primary.metric]
  const spot = ROLE_SPOT[role] ?? { x: 50, y: 50 }

  const detail = Object.entries(metrics)
    .filter(([key]) => key in METRIC_LABEL)
    .slice(0, 3)
    .map(([key, raw]) => ({
      label: METRIC_LABEL[key].label,
      value: `${raw}${METRIC_LABEL[key].unit}`,
    }))

  return {
    id: dto.device_id,
    name: dto.name,
    role: ROLE_LABEL[role] ?? role,
    status: stateOf(dto),
    place: dto.location ?? 'A区茶垄',
    reading: value === undefined ? (dto.online ? '在线' : '离线') : fmt(value, primary.unit),
    detail: detail.length ? detail : [{ label: '状态', value: dto.state }],
    seriesName: primary.label,
    unit: primary.unit,
    series: [],
    metric: primary.metric,
    isMock: dto.is_mock,
    x: spot.x,
    y: spot.y,
  }
}

/**
 * 闭环成功率 / 平均达成率：用 GET /api/verify 最近 20 条记录自己算。
 * 量纲提醒：achievement / confidence 已是 0-100，别再加权乘 100。
 * 一条记录都没有时给 0 并把 hint 写成「还没有验证记录」，不要假装 100%。
 */
async function verifyStats() {
  try {
    const page = await endpoints.verifyList({ page: 1, page_size: 20 })
    const rows = page.items
    if (!rows.length) return { rate: 0, achievement: 0, sample: 0, success: 0 }
    const success = rows.filter((row) => row.conclusion === 'success').length
    const scored = rows.map((row) => row.achievement).filter((value): value is number => typeof value === 'number')
    const mean = scored.length ? scored.reduce((sum, value) => sum + value, 0) / scored.length : 0
    return {
      rate: Math.round((success / rows.length) * 1000) / 10,
      achievement: Math.round(mean * 10) / 10,
      sample: rows.length,
      success,
    }
  } catch {
    return { rate: 0, achievement: 0, sample: 0, success: 0 }
  }
}

export type DashboardData = {
  devices: Device[]
  metrics: Metric[]
  soilSeries: number[]
  soilCurrent: number | null
  source: 'live' | 'mock'
  loading: boolean
  error: string | null
  refresh: () => void
}

export function useDashboard(): DashboardData {
  const [devices, setDevices] = useState<Device[]>(fallbackDevices)
  const [metrics, setMetrics] = useState<Metric[]>(() => fallbackMetrics.map((item) => ({ ...item })))
  const [soilSeries, setSoilSeries] = useState<number[]>(soilDay)
  const [source, setSource] = useState<'live' | 'mock'>('mock')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const rawRef = useRef<{ device: DeviceDto; latest?: SensorLatestDto }[]>([])
  const seriesRef = useRef<Record<string, number[]>>({})
  const tickRef = useRef(0)

  const rebuild = useCallback(() => {
    const view = rawRef.current.map((item) => {
      const mapped = toView(item.device, item.latest)
      const series = seriesRef.current[item.device.device_id]
      return series && series.length > 1 ? { ...mapped, series } : mapped
    })
    if (view.length) setDevices(view)
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [deviceList, latestList] = await Promise.all([endpoints.devices(), endpoints.sensorLatest()])
      const latestBy = new Map(latestList.map((item) => [item.device_id, item]))
      rawRef.current = deviceList.map((device) => ({ device, latest: latestBy.get(device.device_id) }))

      // 曲线：把首屏最新值塞进各自的缓冲，之后靠 WS telemetry 续
      for (const item of latestList) {
        const primary = ROLE_PRIMARY[String(item.role)] ?? ROLE_PRIMARY.field
        const value = item.metrics?.[primary.metric]
        if (typeof value !== 'number') continue
        const buffer = seriesRef.current[item.device_id] ?? []
        buffer.push(value)
        seriesRef.current[item.device_id] = buffer.slice(-24)
      }

      const soil = latestList.find((item) => item.role === 'soil')
      if (soil?.metrics?.soil_moisture !== undefined) {
        const seeded = seriesRef.current[soil.device_id]
        if (seeded && seeded.length > 1) setSoilSeries(seeded)
        else setSoilSeries([soil.metrics.soil_moisture])
      }

      // 指标卡：在线数 / 任务数来自各自接口；闭环成功率与平均达成率
      // 用 GET /api/verify 的最近 N 条记录聚合（后端没有专门的统计接口）
      const online = deviceList.filter((device) => device.online).length
      let taskTotal = 0
      try {
        const page = await endpoints.tasks({ page: 1, page_size: 1 })
        taskTotal = page.total
      } catch {
        /* 任务接口挂了不影响大屏 */
      }

      const stats = await verifyStats()

      setMetrics([
        { id: 'online', label: '在线设备', value: online, suffix: '', hint: `共 ${deviceList.length} 台` },
        { id: 'tasks', label: '今日任务', value: taskTotal, suffix: '', hint: '打开任务中心查看' },
        {
          id: 'loop',
          label: '闭环成功率',
          value: stats.rate,
          suffix: '%',
          hint: stats.sample ? `最近 ${stats.sample} 次验证 · 成功 ${stats.success} 次` : '还没有验证记录',
        },
        {
          id: 'rate',
          label: '平均达成率',
          value: stats.achievement,
          suffix: '%',
          hint: stats.sample ? '验证官复测计算（0-100 量纲）' : '还没有验证记录',
        },
      ])

      rebuild()
      setSource('live')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '数据加载失败')
      setSource('mock')
      setDevices(fallbackDevices)
      setMetrics(fallbackMetrics.map((item) => ({ ...item })))
      setSoilSeries(soilDay)
    } finally {
      setLoading(false)
    }
    // metrics/devices 只作为回退参照，不参与触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rebuild])

  useEffect(() => {
    void load()
  }, [load])

  // WS 遥测：按 device_id 累加曲线 + 刷新读数（20 秒窗口外的抖动不丢，靠时间戳去重交给后端 seq）
  useEffect(() => {
    const off = dashboardSocket.on<{ device_id: string; metrics: Record<string, number> }>(
      'telemetry',
      (data) => {
        const target = rawRef.current.find((item) => item.device.device_id === data.device_id)
        if (!target) return
        const role = String(target.device.role)
        const primary = ROLE_PRIMARY[role] ?? ROLE_PRIMARY.field
        const value = data.metrics?.[primary.metric]

        target.latest = {
          device_id: data.device_id,
          name: target.device.name,
          role,
          is_mock: target.device.is_mock,
          online: true,
          metrics: { ...(target.latest?.metrics ?? {}), ...data.metrics },
          ts: new Date().toISOString(),
        }

        if (typeof value === 'number') {
          const buffer = seriesRef.current[data.device_id] ?? []
          buffer.push(value)
          seriesRef.current[data.device_id] = buffer.slice(-24)
          if (role === 'soil') setSoilSeries([...seriesRef.current[data.device_id]])
        }

        tickRef.current += 1
        // 半秒合并一次，避免高频遥测把 React 刷爆
        if (tickRef.current % 8 === 0) rebuild()
      },
    )

    const offStatus = dashboardSocket.on<DeviceDto>('device_status', (data) => {
      const target = rawRef.current.find((item) => item.device.device_id === data.device_id)
      if (!target) return
      target.device = { ...target.device, ...data }
      rebuild()
    })

    return () => {
      off()
      offStatus()
    }
  }, [rebuild])

  const soilCurrent = soilSeries.length ? soilSeries[soilSeries.length - 1] : null

  return { devices, metrics, soilSeries, soilCurrent, source, loading, error, refresh: () => void load() }
}
