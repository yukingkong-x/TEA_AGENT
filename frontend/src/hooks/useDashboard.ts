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

/**
 * 实时面板要的字段 —— 逐个对应 `firmware/k10_rs485/src/main.cpp` 的 `metrics` 键，
 * 面板上出现任何一个后端收不到的字段，就等于在自己造数。
 * 注意 `noise`（噪音）是参考项目遗留：茶园没有这个语义，面板不展示。
 */
export const FEED_KEYS = [
  'soil_moisture',
  'temperature_c',
  'humidity_air',
  'lux',
  'soil_temp',
  'wind_speed',
  'pressure',
] as const

/** 一条指标的时间序列；`ts` 是本地毫秒时间戳，用来算「几秒前」 */
export type MetricFeed = {
  value: number | null
  series: number[]
  ts: number | null
  deviceId: string | null
  isMock: boolean
}

/**
 * 24h 摘要（GET /api/sensor/day，10 分钟桶）：metric key → 降采样序列 + 窗口极值。
 * 卡片里的日高日低 / DLI / 3h 变压 / 露点副线都从它算，实时 feed 只管最新值与短趋势。
 */
export type DayMetric = {
  points: { ts: string; value: number }[]
  min: number
  max: number
  count: number
}
export type DaySummary = Record<string, DayMetric>

export type SensorLink = {
  lastTs: number | null
  rssi: number | null
  isMock: boolean
}

/** 缓存点数：10 秒一条 → 36 点约 6 分钟，卡片里的迷你曲线够看趋势 */
const FEED_POINTS = 36

/**
 * 脏读数门槛（RS485 调试期）：
 * - ≤ -100 是入库前没拦干净的哨兵值（-999），当前值和曲线都不能用；
 * - 土壤含水率 ≤ 0.5 是「探头未插入」：当前值要留下来让面板说清原因，
 *   但不能进曲线——插进去那一刻会画出一道 0→30% 的假断崖。
 */
function saneValue(value: number): boolean {
  return Number.isFinite(value) && value > -100
}

function saneSeries(metric: string, value: number): boolean {
  if (!saneValue(value)) return false
  if (metric === 'soil_moisture' && value <= 0.5) return false
  return true
}

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
  /** 实时面板：metric key → 最新值 + 短窗口序列 */
  feed: Record<string, MetricFeed>
  /** 24h 摘要：metric key → 降采样序列 + 极值（拉不到就是空对象，卡片自己回退实时序列） */
  day: DaySummary
  link: SensorLink
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
  const feedRef = useRef<Record<string, MetricFeed>>({})
  const [feed, setFeed] = useState<Record<string, MetricFeed>>({})
  const [day, setDay] = useState<DaySummary>({})
  const [link, setLink] = useState<SensorLink>({ lastTs: null, rssi: null, isMock: false })

  /**
   * 把一帧遥测灌进面板缓冲。
   * 面板和地图共用同一份 WS，不另开轮询——两套数据源迟早会在页面上打架。
   */
  const pushFeed = useCallback(
    (deviceId: string, metrics: Record<string, number>, ts: number | null, isMock: boolean) => {
      let touched = false
      for (const key of FEED_KEYS) {
        const raw = metrics[key]
        if (typeof raw !== 'number' || !saneValue(raw)) continue
        const prev = feedRef.current[key]
        // 旧帧不许盖新帧：模拟器停掉之后还可能飘来一两帧残留，
        // 时间戳落后当前值 1 秒以上的一律丢弃，真机读数才不会被回冲。
        if (prev?.ts != null && (ts ?? Date.now()) < prev.ts - 1000) continue
        // 换设备就重开一段曲线：实机与模拟器同时在跑时，混在一张图里会画出
        // 「0℃ → 23℃」的假跳变（首屏尤其明显），delta 也就成了假的。
        const base = prev && prev.deviceId === deviceId ? prev.series : []
        feedRef.current[key] = {
          value: raw,
          series: saneSeries(key, raw) ? [...base, raw].slice(-FEED_POINTS) : base,
          ts: ts ?? Date.now(),
          deviceId,
          isMock,
        }
        touched = true
      }
      if (touched) setFeed({ ...feedRef.current })
    },
    [],
  )

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

      // 实时面板与地图共用同一份 latest。刷新/重连时清空缓冲，
      // 否则上一次会话的曲线会和新数据接在一起，迷你图会出现「断崖」。
      feedRef.current = {}
      /**
       * 真机读数优先：模拟器停掉之后，库里还留着它最后一次的 latest，
       * 直接按返回顺序灌进去会让「31.3% 的模拟土壤湿度」盖掉真机的 0%。
       * 按 is_mock 升序处理（模拟先写、真机后写），同一指标永远是真机赢。
       */
      const ordered = [...latestList].sort(
        (a, b) => Number(Boolean(a.is_mock)) - Number(Boolean(b.is_mock)),
      )
      let latestTs: number | null = null
      for (const item of ordered) {
        const parsed = item.ts ? Date.parse(item.ts) : NaN
        const tsMs = Number.isNaN(parsed) ? null : parsed
        if (tsMs !== null) latestTs = Math.max(latestTs ?? 0, tsMs)
        pushFeed(item.device_id, item.metrics ?? {}, tsMs, Boolean(item.is_mock))
      }
      // rssi 只在 WS 心跳里带，首屏拿不到就先显示 —
      // 模拟角标也只看「最终生效的那份读数」，不看库里有没有模拟设备
      setLink({
        lastTs: latestTs,
        rssi: null,
        isMock: Object.values(feedRef.current).some((item) => item.isMock),
      })

      // 面板曲线种子：REST 只给最新一条，刷新后头半分钟迷你图全是空白占位，
      // 演示前一刷新就露怯。拉一次最近 12 分钟的 history 把曲线填满，
      // 之后 WS 接管（每帧 15s 间隔，36 点 ≈ 9 分钟窗口）。
      try {
        await Promise.all(
          FEED_KEYS.map((key) => {
            const entry = feedRef.current[key]
            if (!entry?.deviceId) return Promise.resolve()
            return endpoints
              .sensorHistory(entry.deviceId, key, 0.2, FEED_POINTS)
              .then((res) => {
                const values = res.points.map((p) => p.value)
                const current = feedRef.current[key]
                if (values.length < 2 || !current) return
                feedRef.current[key] = {
                  ...current,
                  series: [...values, ...current.series].slice(-FEED_POINTS),
                }
              })
              .catch(() => undefined)
          }),
        )
        setFeed({ ...feedRef.current })
      } catch {
        /* 历史接口失败不影响首屏，曲线随后靠 WS 自己攒 */
      }

      // 24h 摘要：每台设备一条请求（10 分钟桶），卡片算日高日低 / DLI / 3h 变压 / 露点。
      // 拉不到就保持空对象——卡片会回退到实时短序列，不许造假数据。
      try {
        const byDevice = new Map<string, string[]>()
        for (const key of FEED_KEYS) {
          const deviceId = feedRef.current[key]?.deviceId
          if (!deviceId) continue
          byDevice.set(deviceId, [...(byDevice.get(deviceId) ?? []), key])
        }
        const merged: DaySummary = {}
        await Promise.all(
          [...byDevice.keys()].map((deviceId) =>
            endpoints
              .sensorDay(deviceId)
              .then((res) => {
                for (const key of byDevice.get(deviceId) ?? []) {
                  const metric = res.metrics[key]
                  if (metric && metric.points.length > 1) merged[key] = metric
                }
              })
              .catch(() => undefined),
          ),
        )
        setDay(merged)
      } catch {
        /* 摘要接口失败不影响首屏 */
      }

      // 曲线：把首屏最新值塞进各自的缓冲，之后靠 WS telemetry 续
      for (const item of ordered) {
        const primary = ROLE_PRIMARY[String(item.role)] ?? ROLE_PRIMARY.field
        const value = item.metrics?.[primary.metric]
        if (typeof value !== 'number' || !saneSeries(primary.metric, value)) continue
        const buffer = seriesRef.current[item.device_id] ?? []
        buffer.push(value)
        seriesRef.current[item.device_id] = buffer.slice(-24)
      }

      const soil = latestList.find((item) => item.role === 'soil')
      const soilNow = soil?.metrics?.soil_moisture
      if (soil && typeof soilNow === 'number' && saneSeries('soil_moisture', soilNow)) {
        const seeded = seriesRef.current[soil.device_id]
        if (seeded && seeded.length > 1) setSoilSeries(seeded)
        else setSoilSeries([soilNow])
      }

      // 指标卡：在线数 / 任务数来自各自接口；闭环成功率与平均达成率
      // 用 GET /api/verify 的最近 N 条记录聚合（后端没有专门的统计接口）
      const online = deviceList.filter((device) => device.online).length
      // 在线数分母只算真机：mock-* 的历史记录还在设备表里，会把「共 N 台」撑大
      const realTotal = deviceList.filter((device) => !device.is_mock).length
      let taskTotal = 0
      try {
        const page = await endpoints.tasks({ page: 1, page_size: 1 })
        taskTotal = page.total
      } catch {
        /* 任务接口挂了不影响大屏 */
      }

      const stats = await verifyStats()

      setMetrics([
        { id: 'online', label: '在线设备', value: online, suffix: '', hint: `共 ${realTotal} 台` },
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
    const off = dashboardSocket.on<{
      device_id: string
      metrics: Record<string, number>
      rssi?: number | null
      ts?: number
    }>(
      'telemetry',
      (data) => {
        const target = rawRef.current.find((item) => item.device.device_id === data.device_id)
        if (!target) return

        // 面板：整帧全字段入缓冲（不再只挑主指标），ts 由后端收敛过，脏值已在入库前被替换
        const tsMs = typeof data.ts === 'number' ? data.ts * 1000 : Date.now()
        pushFeed(data.device_id, data.metrics ?? {}, tsMs, Boolean(target.device.is_mock))
        setLink((prev) => ({
          lastTs: Math.max(prev.lastTs ?? 0, tsMs),
          rssi: typeof data.rssi === 'number' ? data.rssi : prev.rssi,
          isMock: Boolean(target.device.is_mock),
        }))
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

        if (typeof value === 'number' && saneSeries(primary.metric, value)) {
          const buffer = seriesRef.current[data.device_id] ?? []
          buffer.push(value)
          seriesRef.current[data.device_id] = buffer.slice(-24)
          if (role === 'soil') setSoilSeries([...seriesRef.current[data.device_id]])
        }

        tickRef.current += 1
        // 固件 10 秒一帧，地图每两帧刷一次足够；面板（feed）是每帧即刷的
        if (tickRef.current % 2 === 0) rebuild()
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
  }, [rebuild, pushFeed])

  const soilCurrent = soilSeries.length ? soilSeries[soilSeries.length - 1] : null

  return {
    devices,
    metrics,
    soilSeries,
    soilCurrent,
    feed,
    day,
    link,
    source,
    loading,
    error,
    refresh: () => void load(),
  }
}
