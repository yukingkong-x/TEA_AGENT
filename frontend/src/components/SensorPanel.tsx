/**
 * 实时传感器面板（总控页第一屏）—— v3 按参数语义重设计。
 *
 * 设计约束（别改坏）：
 * 1. **字段必须来自固件真实报文**（`firmware/k10_rs485/src/main.cpp`）：
 *    气温/空气湿度/光照/气压/风速 + 土壤含水率/土壤温度。噪音不展示。
 * 2. **每张卡的图形按参数自己的判读逻辑选形式**（参考 dashboard-redesign-demo.html）：
 *    · 土壤含水率 → 阈值分区半环仪表 + 缺水线趋势（唯一有 0-100 自然刻度、驱动灌溉决策）
 *    · 气温       → 适宜带折线（18-28℃）+ 窗口高/低点
 *    · 空气湿度   → 适宜带折线（55-75%）+ 露点虚线副线（Magnus 公式推算）
 *    · 土壤温度   → 土温 vs 气温双线对比（单看土温是一条直线）
 *    · 风速       → 蒲福风级刻度条（13 格）+ 迷你趋势（m/s 没体感，风级才可判读）
 *    · 气压       → 趋势面积图 + 高/低点 + 3h 变压判读（价值在变化率不在绝对值）
 *    · 光照       → 日弧金色面积图 + 光饱和参考线 + DLI 日累计条
 * 3. **主视觉不绑死在某个指标上**：左上两格是「主卡槽」，拖任意卡片进主卡槽就放大成主视觉。
 *    主卡数字 #B8860B / 主折线 #C08A12，其余卡片白数字 + 各自语义色折线。
 * 4. **未插土读数是 0%，不是「极度干旱」**：`soil_moisture <= 0.5` 一律判「探头未插入」。
 * 5. **不自己造数**：24h 序列来自 GET /api/sensor/day（10 分钟桶，后端已滤 -999 哨兵），
 *    拉不到就回退实时短序列；衍生指标（DLI/变压/日高低）只在真有 24h 数据时才报数。
 * 6. **卡片可拖拽**：按住浮起跟随光标，其余卡片 FLIP 平滑让位，松手弹性吸附回网格；
 *    拖进/拖出主卡槽在松手时交换身份。布局持久化在 localStorage（`chaboshi.sensorLayout.v2`）。
 */
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import type { DayMetric, DaySummary, MetricFeed, SensorLink } from '../hooks/useDashboard'
import { GlassCard } from './GlassCard'

type Band = { lo: number; hi: number }

type SensorDef = {
  key: string
  label: string
  unit: string
  digits: number
  hint: string
  /** 适宜带：折线图里铺半透明参考区 */
  band?: Band
  /** 返回告警文案；null 表示正常 */
  judge?: (value: number) => string | null
  /** 曲线上的参考线 */
  guide?: { value: number; label: string }
}

const DRY_LINE = 40

const SENSORS: SensorDef[] = [
  {
    key: 'soil_moisture',
    label: '土壤含水率',
    unit: '%',
    digits: 1,
    hint: '根层探头 · 灌溉决策触发量',
    guide: { value: DRY_LINE, label: '缺水线' },
    judge: (value) => {
      if (value <= 0.5) return '探头未插入'
      if (value < DRY_LINE) return `低于缺水线 ${(DRY_LINE - value).toFixed(1)} 个百分点`
      if (value > 85) return '接近饱和'
      return null
    },
  },
  {
    key: 'temperature_c',
    label: '气温',
    unit: '℃',
    digits: 1,
    hint: '霜冻 / 高温判断',
    band: { lo: 18, hi: 28 },
    judge: (value) => (value < 5 ? '低温' : value > 35 ? '高温' : null),
  },
  {
    key: 'humidity_air',
    label: '空气湿度',
    unit: '%',
    digits: 1,
    hint: '高湿易发病害',
    band: { lo: 55, hi: 75 },
    judge: (value) => (value >= 90 ? '高湿' : value < 40 ? '偏干' : null),
  },
  {
    key: 'lux',
    label: '光照',
    unit: 'lx',
    digits: 0,
    hint: '光合 / 采摘窗口',
  },
  {
    key: 'soil_temp',
    label: '土壤温度',
    unit: '℃',
    digits: 1,
    hint: '根系活性',
  },
  {
    key: 'wind_speed',
    label: '风速',
    unit: 'm/s',
    digits: 1,
    hint: '喷药 / 采摘安全',
    judge: (value) => (value >= 5 ? '偏大' : null),
  },
  {
    key: 'pressure',
    label: '气压',
    unit: 'kPa',
    digits: 1,
    hint: '只看趋势，不参与决策',
  },
]

const LAYOUT_STORAGE_KEY = 'chaboshi.sensorLayout.v2'
const DEFAULT_HERO = 'soil_moisture'

/** 读回持久化布局：主卡 + 小卡顺序，key 集合对得上才采用，对不上就回默认 */
function loadLayout(): { hero: string; order: string[] } {
  const all = SENSORS.map((item) => item.key)
  const fallback: { hero: string; order: string[] } = {
    hero: DEFAULT_HERO,
    order: all.filter((key) => key !== DEFAULT_HERO),
  }
  try {
    const raw = localStorage.getItem(LAYOUT_STORAGE_KEY)
    if (raw) {
      const saved = JSON.parse(raw) as { hero?: unknown; order?: unknown }
      const hero = saved.hero
      const order = saved.order
      if (
        typeof hero === 'string' &&
        all.includes(hero) &&
        Array.isArray(order) &&
        order.length === all.length - 1 &&
        order.every((key) => typeof key === 'string' && all.includes(key)) &&
        !order.includes(hero) &&
        new Set([hero, ...order]).size === all.length
      ) {
        return { hero, order: order as string[] }
      }
    }
    // 旧版（只存顺序、主卡固定土壤含水率）：迁移过来，别让用户之前的排序白调
    const legacyRaw = localStorage.getItem('chaboshi.sensorOrder')
    if (legacyRaw) {
      const legacy = JSON.parse(legacyRaw) as unknown
      if (
        Array.isArray(legacy) &&
        legacy.length === all.length &&
        legacy.every((key) => typeof key === 'string' && all.includes(key)) &&
        new Set(legacy).size === all.length
      ) {
        return { hero: DEFAULT_HERO, order: (legacy as string[]).filter((key) => key !== DEFAULT_HERO) }
      }
    }
  } catch {
    // 解析失败静默回默认，不能让 localStorage 坏数据挡住面板渲染
  }
  return fallback
}

function persistLayout(hero: string, order: string[]) {
  try {
    localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify({ hero, order }))
  } catch {
    // 隐私模式等场景写不进去就算了，不影响功能
  }
}

const reducedMotion = () =>
  typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

const nf = (digits: number) =>
  new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })

function ago(ts: number | null, now: number): string {
  if (!ts) return '—'
  const seconds = Math.max(0, Math.round((now - ts) / 1000))
  if (seconds < 2) return '刚刚'
  if (seconds < 60) return `${seconds} 秒前`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟前`
  return `${Math.round(minutes / 60)} 小时前`
}

/* ==================== 语义色板（对齐茶园主题） ==================== */

const GREEN = '#1F7A45'
const PALE = '#B9D0C2'
const AMBER = '#C08A12'
const GOLD = '#C4942A'
const DEW = '#6B8F7D'
/** 半环仪表 / 风级条的分区色：语义固定，不随主卡变 */
const ZONES = ['#E26D5A', '#E6A817', '#3A9E6F', '#CFE3D6']
const BFT_NAMES = ['静风', '软风', '轻风', '微风', '和风', '清风', '强风', '疾风', '大风', '烈风', '狂风', '暴风', '飓风']
const BFT_MAX = [0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7, 999]
const BFT_COLORS = [
  '#E6EDE9', '#D3E4D9', '#B8D8C5', '#9CCDAF', '#7FBF98', '#5FAE7F', '#3A9E6F',
  '#E6C356', '#E6A817', '#E59D3D', '#E5925A', '#E26D5A', '#D94F43',
]

function bftLevel(value: number): number {
  for (let i = 0; i < BFT_MAX.length; i++) if (value < BFT_MAX[i]) return i
  return 12
}

/** Magnus 公式：温湿度 → 露点（℃） */
function dewpoint(t: number, rh: number): number {
  const g = Math.log(rh / 100) + (17.27 * t) / (t + 237.3)
  return (237.3 * g) / (17.27 - g)
}

/** 饱和水汽压差 VPD（kPa）：>1.2 偏干 / <0.4 偏湿 */
function vpdOf(t: number, rh: number): number {
  const es = 0.6108 * Math.exp((17.27 * t) / (t + 237.3))
  return es * (1 - rh / 100)
}

/** 光照日累计 DLI：1 lx ≈ 0.0182 μmol/m²/s，梯形积分（points 必须带 ts） */
function dliOf(points: { ts: string; value: number }[], bucketMinutes: number): number | null {
  if (points.length < 2) return null
  const stepSec = bucketMinutes * 60
  let sum = 0
  for (let i = 1; i < points.length; i++) {
    const gap = Math.min(Math.abs(Date.parse(points[i].ts) - Date.parse(points[i - 1].ts)) / 1000, stepSec * 3)
    sum += 0.5 * (points[i - 1].value + points[i].value) * gap * 0.0182
  }
  return sum / 1e6
}

/** 按 ts 精确对齐两路 10 分钟桶序列（同一桶宽，时间戳网格一致） */
function alignByTs(
  base: { ts: string; value: number }[],
  ref: { ts: string; value: number }[],
): (number | null)[] | null {
  if (!base.length || !ref.length) return null
  const map = new Map(ref.map((p) => [p.ts, p.value]))
  let hit = 0
  const out = base.map((p) => {
    const value = map.get(p.ts)
    if (value !== undefined) hit += 1
    return value ?? null
  })
  return hit >= 2 ? out : null
}

const dayValues = (metric?: DayMetric) => (metric ? metric.points.map((p) => p.value) : [])

/* ==================== 图形组件（全部手写 SVG/HTML，不引图表库） ==================== */

/**
 * 通用趋势图：主线 + 渐变面积 + 适宜带 + 参考线 + 副线（独立归一）+ 高/低点。
 * SVG 用 preserveAspectRatio="none" 拉满容器；高/低点用 HTML 绝对定位叠加，
 * 避免 SVG 圆点在非等比缩放下被拉成椭圆。
 */
function TrendChart({
  values,
  second,
  band,
  guide,
  markers,
  stroke,
  stroke2 = DEW,
  className = 'h-full w-full',
}: {
  values: number[]
  second?: (number | null)[] | number[] | null
  band?: Band | null
  guide?: { value: number; label: string } | null
  markers?: boolean
  stroke: string
  stroke2?: string
  className?: string
}) {
  const rawId = useId()
  const id = `trend-${rawId.replace(/[^a-zA-Z0-9]/g, '')}`
  if (values.length < 2) {
    return <div className={`${className} rounded-[10px] bg-[#F4F7F5]`} aria-hidden="true" />
  }

  const domain = [...values]
  if (band) domain.push(band.lo, band.hi)
  if (guide) domain.push(guide.value)
  const lo0 = Math.min(...domain)
  const hi0 = Math.max(...domain)
  const pad = (hi0 - lo0) * 0.14 || 1
  const min = lo0 - pad
  const max = hi0 + pad
  const y = (value: number) => 100 - ((value - min) / (max - min)) * 100

  const points = values.map((value, index) => `${(index / (values.length - 1)) * 100},${y(value)}`)
  const line = `M${points.join(' L')}`
  const areaPath = `${line} L100,100 L0,100 Z`

  // 副线（露点/空气温度）独立归一化到自己的量程：虚线细线只看形态不看绝对刻度
  const secondList = second && second.length > 1 ? second : null
  const valid = (secondList ?? []).filter((value): value is number => typeof value === 'number')
  const sMin = valid.length > 1 ? Math.min(...valid) : 0
  const sMax = valid.length > 1 ? Math.max(...valid) : 1
  const sPad = (sMax - sMin) * 0.14 || 1
  const y2 = (value: number) => 100 - ((value - (sMin - sPad)) / (sMax - sMin + 2 * sPad)) * 100
  let secondPath = ''
  if (secondList) {
    const segs: string[] = []
    let seg: string[] = []
    secondList.forEach((value, index) => {
      const x = (index / (secondList.length - 1)) * 100
      if (typeof value !== 'number') {
        if (seg.length > 1) segs.push(`M${seg.join(' L')}`)
        seg = []
        return
      }
      seg.push(`${x},${y2(value)}`)
    })
    if (seg.length > 1) segs.push(`M${seg.join(' L')}`)
    secondPath = segs.join(' ')
  }

  // 高/低点：HTML 圆点叠加
  const hiIdx = values.indexOf(Math.max(...values))
  const loIdx = values.indexOf(Math.min(...values))
  const dot = (index: number) => ({
    left: `${(index / (values.length - 1)) * 100}%`,
    top: `${y(values[index])}%`,
  })

  return (
    <div className={`relative ${className}`}>
      <svg className="h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.20" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>
        {band ? (
          <rect
            x="0"
            y={y(band.hi)}
            width="100"
            height={Math.max(0.5, y(band.lo) - y(band.hi))}
            fill="rgba(31,122,69,0.08)"
          />
        ) : null}
        <path d={areaPath} fill={`url(#${id})`} />
        {guide ? (
          <line
            x1="0"
            y1={y(guide.value)}
            x2="100"
            y2={y(guide.value)}
            stroke="#E4B423"
            strokeWidth="1"
            strokeDasharray="3 3"
            vectorEffect="non-scaling-stroke"
            opacity="0.9"
          />
        ) : null}
        {secondPath ? (
          <path
            d={secondPath}
            fill="none"
            stroke={stroke2}
            strokeWidth="1.2"
            strokeDasharray="4 3"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
            opacity="0.85"
          />
        ) : null}
        <path
          d={line}
          fill="none"
          stroke={stroke}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {markers ? (
        <>
          <span
            className="absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white bg-[rgba(46,125,91,0.9)]"
            style={dot(hiIdx)}
            title={`高 ${Math.max(...values).toFixed(1)}`}
          />
          <span
            className="absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-white bg-[rgba(46,125,91,0.55)]"
            style={dot(loIdx)}
            title={`低 ${Math.min(...values).toFixed(1)}`}
          />
        </>
      ) : null}
    </div>
  )
}

/** 土壤含水率半环仪表：0-100 分区（红<20 黄20-40 绿40-70 浅绿>70）+ 指针 */
function MoistureGauge({ value, hero }: { value: number | null; hero: boolean }) {
  const cx = 60
  const cy = 56
  const r = 44
  const strokeW = hero ? 11 : 9
  const arc = (from: number, to: number) => {
    // 含水率 v → 极角 θ(v) = 180 - 1.8v（度）；180° 在左端，0° 在右端
    const a0 = ((180 - from * 1.8) * Math.PI) / 180
    const a1 = ((180 - to * 1.8) * Math.PI) / 180
    const p0 = `${cx + r * Math.cos(a0)},${cy - r * Math.sin(a0)}`
    const p1 = `${cx + r * Math.cos(a1)},${cy - r * Math.sin(a1)}`
    return `M${p0} A${r} ${r} 0 0 1 ${p1}`
  }
  const shown = value !== null && value > 0.5 ? Math.max(0, Math.min(100, value)) : null
  const needleAngle = shown === null ? null : ((180 - shown * 1.8) * Math.PI) / 180
  return (
    <svg className="h-full w-full" viewBox="0 0 120 70" aria-hidden="true">
      {(
        [
          [0, 20],
          [20, 40],
          [40, 70],
          [70, 100],
        ] as [number, number][]
      ).map(([from, to], index) => (
        <path
          key={from}
          d={arc(from, to)}
          fill="none"
          stroke={ZONES[index]}
          strokeWidth={strokeW}
          strokeLinecap="butt"
        />
      ))}
      {needleAngle !== null ? (
        <>
          <line
            x1={cx}
            y1={cy}
            x2={cx + r * 0.58 * Math.cos(needleAngle)}
            y2={cy - r * 0.58 * Math.sin(needleAngle)}
            stroke="#55645B"
            strokeWidth="3"
            strokeLinecap="round"
          />
          <circle cx={cx} cy={cy} r="4" fill="#55645B" />
        </>
      ) : (
        <text x={cx} y={cy - 6} textAnchor="middle" fontSize="9" fill="#9AA8A0">
          等待上报
        </text>
      )}
      <text x={cx - r} y={cy + 10} textAnchor="middle" fontSize="7.5" fill="#9AA8A0">
        0
      </text>
      <text x={cx} y={cy - r - 2} textAnchor="middle" fontSize="7.5" fill="#9AA8A0">
        50
      </text>
      <text x={cx + r} y={cy + 10} textAnchor="middle" fontSize="7.5" fill="#9AA8A0">
        100
      </text>
    </svg>
  )
}

/** 蒲福风级刻度条：13 格 + 当前级高亮 + ▲ 指示 */
function BeaufortStrip({ level }: { level: number }) {
  return (
    <div className="w-full">
      <div className="flex gap-[2px]" style={{ height: 12 }}>
        {BFT_COLORS.map((color, index) => (
          <div
            key={index}
            className={`flex-1 rounded-[3px] transition-transform duration-150 ${
              index === level ? 'scale-y-[1.4] ring-1 ring-[#55645B]/50' : ''
            }`}
            style={{ background: color }}
            title={`${index}级 ${BFT_NAMES[index]}`}
          />
        ))}
      </div>
      <div className="relative mt-0.5 h-3 text-[9px] font-semibold text-[#1F2A24]">
        <span
          className="absolute -translate-x-1/2 whitespace-nowrap"
          style={{ left: `${((level + 0.5) / 13) * 100}%` }}
        >
          ▲ {level}级
        </span>
      </div>
      <div className="flex justify-between text-[9px] text-[#9AA8A0]">
        <span>0级</span>
        <span>3级</span>
        <span>6级</span>
        <span>9级</span>
        <span>12级</span>
      </div>
    </div>
  )
}

/** 光照 DLI 日累计条：0-25 mol/m²，茶树参考带 8-14 */
function DliBar({ dli }: { dli: number | null }) {
  const pct = dli === null ? 0 : Math.min(100, (dli / 25) * 100)
  return (
    <div className="w-full">
      <div className="relative h-2.5 overflow-hidden rounded-[5px] bg-[#F0F3EF]">
        <div
          className="absolute inset-y-0 border-x border-dashed border-[#3A9E6F]"
          style={{ left: `${(8 / 25) * 100}%`, width: `${(6 / 25) * 100}%`, background: 'rgba(58,158,111,0.13)' }}
        />
        {pct > 0 ? (
          <div
            className="absolute inset-y-0 left-0 rounded-l-[5px]"
            style={{ width: `${pct}%`, background: 'linear-gradient(90deg,#ECD9A0,#D9A83C)' }}
          />
        ) : null}
      </div>
      <div className="mt-0.5 flex justify-between text-[9px] text-[#9AA8A0]">
        <span>0</span>
        <span>茶树参考带 8–14</span>
        <span>25 mol/m²</span>
      </div>
    </div>
  )
}

/** 图例小圆点行 */
function LegendDots({ items }: { items: { color: string; label: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] leading-none text-mute">
      {items.map((item) => (
        <span key={item.label} className="inline-flex items-center gap-1">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  )
}

/* ==================== 卡片 ==================== */

function ReadingCard({
  def,
  feed,
  allFeeds,
  day,
  now,
  hero,
  hinted,
  dragging,
  registerRef,
  onPointerDown,
}: {
  def: SensorDef
  feed?: MetricFeed
  allFeeds: Record<string, MetricFeed>
  day: DaySummary
  now: number
  /** 是否占据主卡槽（左上两格）：大数字、大图形 */
  hero: boolean
  /** 拖拽悬停提示：松手会把这张卡换上/换下主卡槽 */
  hinted: boolean
  dragging: boolean
  registerRef: (key: string, el: HTMLElement | null) => void
  onPointerDown: (key: string, event: React.PointerEvent<HTMLElement>) => void
}) {
  const value = typeof feed?.value === 'number' ? feed.value : null
  const series = feed?.series ?? []
  const digits = nf(def.digits)
  const previous = series.length > 1 ? series[series.length - 2] : null
  const delta = value !== null && previous !== null ? value - previous : null
  /** 按显示精度收敛后的变化量：0.04 显示成 0.0 时不该再画个箭头 */
  const shownDelta = delta === null ? null : Number(Math.abs(delta).toFixed(def.digits))
  const deltaText =
    shownDelta === null
      ? null
      : shownDelta === 0
        ? '持平'
        : `${delta !== null && delta > 0 ? '▲' : '▼'} ${digits.format(shownDelta)}`
  const alert = value !== null && def.judge ? def.judge(value) : null
  /**
   * 颜色规则：只有占主卡槽的卡片数字是琥珀色，其余一律白数字；
   * 主折线同样跟随主卡身份；告警只走右上角徽章，不给数字/折线额外变色。
   */
  const mainStroke = hero ? AMBER : GREEN
  const stale = feed?.ts != null ? now - feed.ts > 45_000 : false
  const idle = value === null

  const dayMetric = day[def.key]
  /** 图形序列：优先 24h 降采样（点够 6 个才像条曲线），否则回退实时短序列 */
  const dayVals = dayValues(dayMetric)
  const useDay = dayVals.length >= 6
  const chartValues = useDay ? dayVals : series

  /* ---------- 副行文案：每个参数报自己真正可判读的信息 ---------- */
  const timeTag = (
    <span className={`num shrink-0 tabular-nums ${stale ? 'text-[#8A6414]' : 'text-[#A9B4BF]'}`}>
      {stale ? `停更 ${ago(feed?.ts ?? null, now)}` : ago(feed?.ts ?? null, now)}
    </span>
  )
  /* ---------- 数字行右侧的衍生胶囊：由真实数据现算，算不出就不显示 ---------- */
  const pills: React.ReactNode[] = []
  let press3h: number | null = null
  if (def.key === 'humidity_air') {
    const tempValue = allFeeds.temperature_c?.value
    const dew = value !== null && typeof tempValue === 'number' ? dewpoint(tempValue, value) : null
    const vpd = dew !== null && typeof tempValue === 'number' && value !== null ? vpdOf(tempValue, value) : null
    if (dew !== null) {
      pills.push(
        <span
          key="dew"
          className="num inline-flex shrink-0 items-center rounded-full bg-[#EEF5F0] px-2 py-0.5 text-[11px] font-medium leading-none tabular-nums text-[#2E7D5B]"
          title="露点：由气温/湿度按 Magnus 公式推算"
        >
          露点 {dew.toFixed(1)}℃
        </span>,
      )
    }
    if (vpd !== null) {
      const off = vpd > 1.2 || vpd < 0.4
      pills.push(
        <span
          key="vpd"
          title="VPD（饱和水汽压差）：<0.4 偏湿易发病害，>1.2 偏干蒸腾强"
          className={`num inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-medium leading-none tabular-nums ${
            off ? 'border border-[#F0DCA8] bg-[#FDF3DD] text-[#B07A10]' : 'bg-[#EEF5F0] text-[#2E7D5B]'
          }`}
        >
          VPD {vpd.toFixed(2)}
        </span>,
      )
    }
  } else if (def.key === 'pressure') {
    if (useDay && dayMetric && dayMetric.points.length > 2) {
      const pts = dayMetric.points
      const target = Date.now() - 3 * 3600_000
      let best = pts[0]
      for (const p of pts) {
        if (Math.abs(Date.parse(p.ts) - target) < Math.abs(Date.parse(best.ts) - target)) best = p
      }
      press3h = pts[pts.length - 1].value - best.value
    }
    if (press3h !== null) {
      const calm = Math.abs(press3h) <= 0.3
      pills.push(
        <span
          key="p3h"
          title="3 小时变压：短临天气信号，骤降注意风雨"
          className={`num inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-medium leading-none tabular-nums ${
            calm ? 'bg-[#EEF5F0] text-[#2E7D5B]' : 'border border-[#F0DCA8] bg-[#FDF3DD] text-[#B07A10]'
          }`}
        >
          3h {press3h >= 0 ? '+' : ''}
          {press3h.toFixed(2)} kPa
        </span>,
      )
    }
  }

  let sub: React.ReactNode
  if (def.key === 'temperature_c') {
    const hi = chartValues.length ? Math.max(...chartValues) : null
    const lo = chartValues.length ? Math.min(...chartValues) : null
    sub = (
      <>
        <span className="num tabular-nums">
          {hi !== null && lo !== null
            ? `${useDay ? '日' : '近期'}高 ${hi.toFixed(1)}° / ${useDay ? '日' : '近期'}低 ${lo.toFixed(1)}°`
            : def.hint}
        </span>
        {timeTag}
      </>
    )
  } else if (def.key === 'humidity_air') {
    sub = (
      <>
        <span>{idle ? '等待设备上报' : '适宜带 55–75% · 高湿易发病害'}</span>
        {timeTag}
      </>
    )
  } else if (def.key === 'soil_temp') {
    sub = (
      <>
        <span>{idle ? '等待设备上报' : def.hint}</span>
        {timeTag}
      </>
    )
  } else if (def.key === 'wind_speed') {
    const lv = value !== null ? bftLevel(value) : null
    const lo = lv !== null && lv > 0 ? BFT_MAX[lv - 1].toFixed(1) : '0'
    const hi = lv !== null ? (BFT_MAX[lv] - 0.1).toFixed(1) : null
    sub = (
      <>
        <span className="num tabular-nums">
          {lv !== null && hi !== null ? `蒲福 ${lv}级 · ${BFT_NAMES[lv]}（${lo}–${hi} m/s）` : def.hint}
        </span>
        {timeTag}
      </>
    )
  } else if (def.key === 'pressure') {
    sub = (
      <>
        <span className="num tabular-nums">
          {press3h !== null
            ? press3h > 0.3
              ? '变压回升趋稳'
              : press3h < -0.3
                ? '变压下降，注意天气'
                : '变压平稳'
            : '3h 变压需 24h 数据积累'}
        </span>
        {timeTag}
      </>
    )
  } else if (def.key === 'lux') {
    const dli = useDay && dayMetric ? dliOf(dayMetric.points, 10) : null
    sub = (
      <>
        <span className="num tabular-nums">
          {dli !== null ? `日累计 DLI ≈ ${dli.toFixed(1)} mol/m²（估算）` : 'DLI — · 需 24h 数据积累'}
        </span>
        {timeTag}
      </>
    )
  } else {
    sub = (
      <>
        <span>{idle ? '等待设备上报' : def.hint}</span>
        {timeTag}
      </>
    )
  }

  /* ---------- 图形区：每个参数一种形式；高度固定档位（对齐 demo：小 148 / 主 196 / spark 50），mt-auto 贴卡片底 ---------- */
  let visual: React.ReactNode
  if (def.key === 'soil_moisture') {
    visual = (
      <div className="mt-auto flex shrink-0 flex-col">
        <div className={`${hero ? 'h-[170px]' : 'h-[130px]'} shrink-0`}>
          <MoistureGauge value={value} hero={hero} />
        </div>
        <div className="mt-1 shrink-0">
          <LegendDots
            items={[
              { color: ZONES[0], label: '重度缺水<20' },
              { color: ZONES[1], label: '缺水20–40' },
              { color: ZONES[2], label: '适宜40–70' },
              { color: ZONES[3], label: '偏湿>70' },
            ]}
          />
        </div>
        <div className="mt-1.5 h-[50px] shrink-0">
          <TrendChart values={chartValues} guide={def.guide} stroke={mainStroke} />
        </div>
      </div>
    )
  } else if (def.key === 'temperature_c') {
    visual = (
      <div className={`${hero ? 'h-[196px]' : 'h-[148px]'} mt-auto shrink-0`}>
        <TrendChart values={chartValues} band={def.band ?? null} stroke={mainStroke} markers />
      </div>
    )
  } else if (def.key === 'humidity_air') {
    // 露点副线：气温 24h 序列按桶时间戳对齐湿度序列（同一桶网格）
    const tempDay = day.temperature_c
    let dewSeries: (number | null)[] | null = null
    if (useDay && dayMetric && tempDay && tempDay.points.length >= 6) {
      const aligned = alignByTs(dayMetric.points, tempDay.points)
      if (aligned) {
        dewSeries = dayMetric.points.map((p, index) => {
          const t = aligned[index]
          return t === null ? null : dewpoint(t, p.value)
        })
      }
    }
    visual = (
      <div className="mt-auto shrink-0">
        <div className={`${hero ? 'h-[196px]' : 'h-[148px]'}`}>
          <TrendChart
            values={chartValues}
            second={dewSeries}
            band={def.band ?? null}
            stroke={mainStroke}
            stroke2={DEW}
          />
        </div>
        <div className="mt-1.5 shrink-0">
          <LegendDots
            items={[
              { color: mainStroke, label: '空气湿度' },
              { color: DEW, label: '露点（虚线）' },
            ]}
          />
        </div>
      </div>
    )
  } else if (def.key === 'soil_temp') {
    const soilDayVals = dayValues(day.soil_temp)
    const airDayVals = dayValues(day.temperature_c)
    let airAligned: number[] | null = null
    if (soilDayVals.length >= 6 && airDayVals.length >= 6) {
      const aligned = alignByTs(day.soil_temp.points, day.temperature_c.points)
      if (aligned) {
        airAligned = aligned.filter((v): v is number => v !== null)
      }
    }
    const soilVals = soilDayVals.length >= 6 ? soilDayVals : series
    const airVals = airAligned ?? allFeeds.temperature_c?.series ?? []
    visual = (
      <div className="mt-auto shrink-0">
        <div className={`${hero ? 'h-[196px]' : 'h-[148px]'}`}>
          <TrendChart
            values={soilVals}
            second={airVals.length > 1 ? airVals : null}
            stroke={mainStroke}
            stroke2={PALE}
          />
        </div>
        <div className="mt-1.5 shrink-0">
          <LegendDots
            items={[
              { color: mainStroke, label: '土壤温度' },
              { color: PALE, label: '空气温度' },
            ]}
          />
        </div>
      </div>
    )
  } else if (def.key === 'wind_speed') {
    const lv =
      value !== null
        ? bftLevel(value)
        : chartValues.length > 0
          ? bftLevel(chartValues[chartValues.length - 1])
          : null
    visual = (
      <div className="mt-auto flex shrink-0 flex-col justify-end gap-1.5">
        {lv !== null ? <BeaufortStrip level={lv} /> : <div className="h-[34px] rounded-[10px] bg-[#F4F7F5]" />}
        <div className="h-[50px]">
          <TrendChart values={chartValues} stroke={mainStroke} />
        </div>
      </div>
    )
  } else if (def.key === 'pressure') {
    visual = (
      <div className={`${hero ? 'h-[196px]' : 'h-[148px]'} mt-auto shrink-0`}>
        <TrendChart values={chartValues} stroke={mainStroke} markers />
      </div>
    )
  } else if (def.key === 'lux') {
    const dli = useDay && dayMetric ? dliOf(dayMetric.points, 10) : null
    // 光饱和线只在数据真摸到 3 万 lx 以上才有参照意义，否则只是空顶部一条线
    const showSat = chartValues.length ? Math.max(...chartValues) >= 30_000 : false
    visual = (
      <div className="mt-auto flex shrink-0 flex-col gap-1.5">
        <div className={hero ? 'h-[150px]' : 'h-[110px]'}>
          <TrendChart
            values={chartValues}
            guide={showSat ? { value: 40_000, label: '光饱和' } : null}
            stroke={hero ? AMBER : GOLD}
          />
        </div>
        <div className="shrink-0">
          <DliBar dli={dli} />
        </div>
      </div>
    )
  } else {
    visual = <div className="mt-auto h-[148px] shrink-0 rounded-[10px] bg-[#F4F7F5]" />
  }

  return (
    <article
      ref={(el) => registerRef(def.key, el)}
      onPointerDown={(event) => onPointerDown(def.key, event)}
      className={`flex touch-none select-none flex-col rounded-card border bg-panel px-4 py-3.5 transition-[border-color,box-shadow] duration-200 ${
        hero ? 'col-span-2' : ''
      } ${alert ? 'border-[#EFDCB6]' : 'border-line'} hover:border-[#CFE3D6] hover:shadow-[0_8px_22px_rgba(22,28,45,0.06)] ${
        hinted && !dragging ? 'ring-2 ring-tea/40 shadow-[0_12px_32px_rgba(31,122,69,0.16)]' : ''
      } ${
        dragging
          ? 'cursor-grabbing shadow-[0_24px_60px_rgba(22,28,45,0.28)] ring-2 ring-tea/30'
          : 'cursor-grab'
      }`}
      aria-label={`${def.label}${value === null ? '，等待上报' : `，${digits.format(value)}${def.unit}`}`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs leading-none text-mute">{def.label}</p>
        {alert ? (
          <span className="shrink-0 rounded-btn bg-[#FFF4CC] px-2 py-0.5 text-[11px] leading-none text-[#6E5314]">
            {alert}
          </span>
        ) : null}
      </div>

      <p className="mt-2 flex items-baseline gap-1.5">
        <span
          className={`num tabular-nums leading-none tracking-[-0.01em] ${
            hero ? 'text-[40px]' : 'text-[33px]'
          } ${idle ? 'text-[#C9CDD4]' : hero ? 'text-[#B8860B]' : 'text-paper'}`}
        >
          {value === null ? '—' : digits.format(value)}
        </span>
        <span className={`text-xs leading-none ${idle ? 'text-[#C9CDD4]' : 'text-mute'}`}>{def.unit}</span>
        {deltaText ? (
          <span
            className={`num text-[11px] font-semibold leading-none tabular-nums ${
              shownDelta === 0 ? 'font-medium text-mute' : delta !== null && delta > 0 ? 'text-[#2E7D5B]' : 'text-[#C77B28]'
            }`}
          >
            {deltaText}
          </span>
        ) : null}
        {pills.length ? <span className="ml-auto flex items-center gap-1.5">{pills}</span> : null}
      </p>

      <p className="mt-1.5 flex items-center gap-2 truncate text-[11px] leading-none text-mute">{sub}</p>

      {visual}
    </article>
  )
}

function LinkPill({ link, now }: { link: SensorLink; now: number }) {
  const fresh = link.lastTs !== null && now - link.lastTs < 60_000
  const weak = link.rssi !== null && link.rssi < -70
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px] leading-none text-mute">
      <span
        className={`inline-flex items-center gap-1.5 rounded-btn px-2 py-1 ${
          fresh ? 'bg-[#E8F5EC] text-[#1F7A45]' : 'bg-[#F2F3F5] text-[#86909C]'
        }`}
        title={fresh ? '最近 1 分钟内有报文' : '超过 1 分钟没有新报文'}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${fresh ? 'bg-[#1F7A45]' : 'bg-[#C9CDD4]'}`} />
        {fresh ? '实时' : '停更'}
      </span>
      <span className="num tabular-nums">最后上报 {ago(link.lastTs, now)}</span>
      <span className="text-[#D5DBE1]">|</span>
      <span className={`num tabular-nums ${weak ? 'text-[#8A6414]' : ''}`}>
        信号 {link.rssi === null ? '—' : `${Math.round(link.rssi)} dBm`}
      </span>
      {link.isMock ? (
        <span
          className="rounded-btn bg-[#FFF4CC] px-2 py-1 text-[#6E5314]"
          title="这批读数来自后端 mock 模拟器，不是实机"
        >
          模拟
        </span>
      ) : null}
    </div>
  )
}

type DragState = {
  key: string
  pointerId: number
  startX: number
  startY: number
  /** 按下点相对卡片左上角的偏移，跟手时保持这个抓取点不漂 */
  offX: number
  offY: number
  /** 激活时卡片在容器内的位置（style.left/top 的值） */
  relLeft: number
  relTop: number
  containerRect: DOMRect
  active: boolean
  holdTimer: number
  /** 松手前最后悬停的卡片 key：落在主卡上（或主卡落在小卡上）就交换身份 */
  hoverKey: string | null
}

export function SensorPanel({
  feed,
  link,
  day,
}: {
  feed: Record<string, MetricFeed>
  link: SensorLink
  day: DaySummary
}) {
  // 相对时间要自己走：数据 10 秒才来一次，但没有秒级 tick 的话「3 秒前」会一直不动
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const boot = useRef<{ hero: string; order: string[] } | null>(null)
  if (!boot.current) boot.current = loadLayout()
  /** 主卡槽里现在的指标：身份跟着槽位走，不绑死在任何一张卡上 */
  const [heroKey, setHeroKey] = useState<string>(boot.current.hero)
  /** 其余 6 张小卡的顺序 */
  const [order, setOrder] = useState<string[]>(boot.current.order)
  const heroRef = useRef(heroKey)
  heroRef.current = heroKey
  const orderRef = useRef(order)
  orderRef.current = order

  const [dragKey, setDragKey] = useState<string | null>(null)
  const dragKeyRef = useRef<string | null>(null)
  dragKeyRef.current = dragKey
  /** 拖拽悬停提示：哪张卡被「松手就换主卡」瞄准了 */
  const [dropHint, setDropHint] = useState<string | null>(null)

  const gridRef = useRef<HTMLDivElement | null>(null)
  const cardsRef = useRef(new Map<string, HTMLElement>())
  /** FLIP 的「第一帧」：每次布局变化前先记下旧位置 */
  const prevRects = useRef(new Map<string, DOMRect>())
  const dragRef = useRef<DragState | null>(null)
  /** 松手吸附：记下卡片松手时的视觉位置/尺寸，等 React 提交新布局后从那里弹性 morph 过去 */
  const pendingSnap = useRef<{
    key: string
    left: number
    top: number
    width: number
    height: number
  } | null>(null)

  const registerRef = (key: string, el: HTMLElement | null) => {
    if (el) cardsRef.current.set(key, el)
    else cardsRef.current.delete(key)
  }

  const recordRects = () => {
    prevRects.current.clear()
    for (const [key, el] of cardsRef.current) prevRects.current.set(key, el.getBoundingClientRect())
  }

  /**
   * FLIP：布局变化后，从旧位置平滑滑到新位置（拖拽中的卡除外，它自己跟手）。
   * 主卡升降级会带来宽高变化，尺寸也从旧值过渡到新值，避免「啪」一下跳变。
   */
  useLayoutEffect(() => {
    if (prevRects.current.size === 0) {
      recordRects()
      return
    }
    const reduce = reducedMotion()
    const snapKey = pendingSnap.current?.key
    for (const [key, el] of cardsRef.current) {
      if (key === dragKeyRef.current || key === snapKey) continue
      const old = prevRects.current.get(key)
      if (!old) continue
      const current = el.getBoundingClientRect()
      const dx = old.left - current.left
      const dy = old.top - current.top
      const dw = old.width - current.width
      const dh = old.height - current.height
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1 && Math.abs(dw) < 1 && Math.abs(dh) < 1) continue
      if (reduce) continue
      el.style.transition = 'none'
      if (Math.abs(dw) > 1) el.style.width = `${old.width}px`
      if (Math.abs(dh) > 1) el.style.height = `${old.height}px`
      el.style.transform = `translate(${dx}px, ${dy}px)`
      // 强制回流，让浏览器记住「从旧位置出发」
      void el.getBoundingClientRect()
      el.style.transition =
        'transform 300ms cubic-bezier(0.22, 1, 0.36, 1), width 300ms cubic-bezier(0.22, 1, 0.36, 1), height 300ms cubic-bezier(0.22, 1, 0.36, 1)'
      el.style.transform = ''
      if (Math.abs(dw) > 1) el.style.width = `${current.width}px`
      if (Math.abs(dh) > 1) el.style.height = `${current.height}px`
      window.setTimeout(() => {
        el.style.transition = ''
        el.style.transform = ''
        el.style.width = ''
        el.style.height = ''
      }, 340)
    }
    recordRects()
  }, [order, heroKey])

  /** 松手吸附：卡片从松手时的视觉位置/尺寸，弹性 morph 到它在新布局里的槽位 */
  useLayoutEffect(() => {
    if (dragKey !== null) return
    const snap = pendingSnap.current
    if (!snap) return
    pendingSnap.current = null
    const el = cardsRef.current.get(snap.key)
    if (!el || reducedMotion()) return
    const target = el.getBoundingClientRect()
    el.style.transition = 'none'
    el.style.width = `${snap.width}px`
    el.style.height = `${snap.height}px`
    el.style.transform = `translate(${snap.left - target.left}px, ${snap.top - target.top}px)`
    void el.getBoundingClientRect()
    // 回弹曲线：冲过目标一点再收回来（和侧边栏胶囊同一族手感）；宽高同步 morph
    el.style.transition =
      'transform 460ms cubic-bezier(0.3, 1.4, 0.4, 1), width 320ms cubic-bezier(0.22, 1, 0.36, 1), height 320ms cubic-bezier(0.22, 1, 0.36, 1)'
    el.style.transform = ''
    el.style.width = `${target.width}px`
    el.style.height = `${target.height}px`
    window.setTimeout(() => {
      el.style.transition = ''
      el.style.transform = ''
      el.style.width = ''
      el.style.height = ''
    }, 520)
  }, [dragKey])

  /** 激活拖拽：卡片脱离文档流浮起（absolute + 跟手），其余卡片 FLIP 让位 */
  const activateDrag = (state: DragState) => {
    const el = cardsRef.current.get(state.key)
    if (!el || !gridRef.current) return
    state.active = true
    state.hoverKey = null
    setDragKey(state.key)
    recordRects()
    const rect = el.getBoundingClientRect()
    const containerRect = gridRef.current.getBoundingClientRect()
    state.containerRect = containerRect
    state.relLeft = rect.left - containerRect.left
    state.relTop = rect.top - containerRect.top
    el.style.position = 'absolute'
    el.style.left = `${state.relLeft}px`
    el.style.top = `${state.relTop}px`
    el.style.width = `${rect.width}px`
    el.style.height = `${rect.height}px`
    el.style.zIndex = '30'
    el.style.margin = '0'
    // 剩余卡片会立刻补位，从记录的旧位置滑过去
    for (const [key, other] of cardsRef.current) {
      if (key === state.key) continue
      const old = prevRects.current.get(key)
      if (!old) continue
      const current = other.getBoundingClientRect()
      const dx = old.left - current.left
      const dy = old.top - current.top
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) continue
      other.style.transition = 'none'
      other.style.transform = `translate(${dx}px, ${dy}px)`
      void other.getBoundingClientRect()
      other.style.transition = 'transform 300ms cubic-bezier(0.22, 1, 0.36, 1)'
      other.style.transform = ''
      window.setTimeout(() => {
        other.style.transition = ''
        other.style.transform = ''
      }, 340)
    }
    recordRects()
    document.body.style.userSelect = 'none'
  }

  const endDrag = (state: DragState) => {
    window.clearTimeout(state.holdTimer)
    document.body.style.userSelect = ''
    setDropHint(null)
    const el = cardsRef.current.get(state.key)
    if (state.active && el && gridRef.current) {
      // 记下松手时卡片的视觉位置/尺寸，恢复文档流后从那里弹性吸附回新槽位
      const visual = el.getBoundingClientRect()

      // 身份交换只发生在松手一刻：
      // · 小卡落在主卡上 → 小卡升级成主卡，原主卡退到小卡原来的槽位
      // · 主卡落在小卡上 → 被指到的小卡升级成主卡，原主卡退到小卡的槽位
      const hover = state.hoverKey
      if (hover && hover !== state.key) {
        if (state.key === heroRef.current) {
          const next = orderRef.current.map((key) => (key === hover ? state.key : key))
          heroRef.current = hover
          orderRef.current = next
          setHeroKey(hover)
          setOrder(next)
        } else if (hover === heroRef.current) {
          const next = orderRef.current.map((key) => (key === state.key ? hover : key))
          heroRef.current = state.key
          orderRef.current = next
          setHeroKey(state.key)
          setOrder(next)
        }
      }

      pendingSnap.current = {
        key: state.key,
        left: visual.left,
        top: visual.top,
        width: visual.width,
        height: visual.height,
      }
      el.style.position = ''
      el.style.left = ''
      el.style.top = ''
      el.style.width = ''
      el.style.height = ''
      el.style.zIndex = ''
      el.style.margin = ''
    }
    dragRef.current = null
    setDragKey(null)
    persistLayout(heroRef.current, orderRef.current)
  }

  const handlePointerDown = (key: string, event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0 || dragRef.current) return
    const el = cardsRef.current.get(key)
    if (!el || !gridRef.current) return
    const rect = el.getBoundingClientRect()
    const state: DragState = {
      key,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      offX: event.clientX - rect.left,
      offY: event.clientY - rect.top,
      relLeft: 0,
      relTop: 0,
      containerRect: gridRef.current.getBoundingClientRect(),
      active: false,
      holdTimer: 0,
      hoverKey: null,
    }
    // 按住 180ms 也算开始拖（不动鼠标也能浮起），挪过 6px 则立刻激活
    state.holdTimer = window.setTimeout(() => activateDrag(state), 180)

    const onMove = (e: PointerEvent) => {
      if (e.pointerId !== state.pointerId) return
      if (!state.active) {
        const dist = Math.hypot(e.clientX - state.startX, e.clientY - state.startY)
        if (dist > 6) {
          window.clearTimeout(state.holdTimer)
          activateDrag(state)
        } else {
          return
        }
      }
      const el = cardsRef.current.get(state.key)
      if (!el) return
      const x = e.clientX - state.offX - state.containerRect.left - state.relLeft
      const y = e.clientY - state.offY - state.containerRect.top - state.relTop
      el.style.transform = `translate(${x}px, ${y}px) scale(1.04)`

      // 指针落在哪张卡上，就瞄准哪张卡（跨行跨列都自然成立）
      let hoveredKey: string | null = null
      let bestDist = Number.POSITIVE_INFINITY
      for (const [otherKey, other] of cardsRef.current) {
        if (otherKey === state.key) continue
        const r = other.getBoundingClientRect()
        if (
          e.clientX >= r.left &&
          e.clientX <= r.right &&
          e.clientY >= r.top &&
          e.clientY <= r.bottom
        ) {
          hoveredKey = otherKey
          break
        }
        const cx = r.left + r.width / 2
        const cy = r.top + r.height / 2
        const d = Math.hypot(e.clientX - cx, e.clientY - cy)
        if (d < bestDist) {
          bestDist = d
          hoveredKey = otherKey
        }
      }
      state.hoverKey = hoveredKey
      setDropHint(hoveredKey)
      if (!hoveredKey) return

      // 主卡被拖时舞台由小卡补位，身份在松手时交换，拖动中不做让位预览
      if (state.key === heroRef.current) return
      // 小卡悬停在主卡上：只高亮主卡槽提示「松手换主卡」，不重排
      if (hoveredKey === heroRef.current) return

      // 小卡之间：实时让位重排
      const current = orderRef.current
      const from = current.indexOf(state.key)
      const to = current.indexOf(hoveredKey)
      if (to === -1 || from === to) return
      recordRects()
      const next = [...current]
      next.splice(from, 1)
      next.splice(to, 0, state.key)
      // 先同步 ref 再 setState：连续两次让位之间 React 可能还没重渲染
      orderRef.current = next
      setOrder(next)
    }

    const onUp = (e: PointerEvent) => {
      if (e.pointerId !== state.pointerId) return
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onCancel)
      endDrag(state)
    }
    const onCancel = () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onCancel)
      endDrag(state)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onCancel)
  }

  const heroDef = SENSORS.find((item) => item.key === heroKey)
  const smallDefs = order
    .map((key) => SENSORS.find((item) => item.key === key))
    .filter((item): item is SensorDef => Boolean(item))
  const orderedDefs = heroDef ? [heroDef, ...smallDefs] : smallDefs

  return (
    <GlassCard className="p-4 sm:p-5" label="实时传感器读数">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <div>
          <h2 className="text-paper">实时传感</h2>
        </div>
        <LinkPill link={link} now={now} />
      </div>

      <div ref={gridRef} className="relative grid auto-rows-fr grid-cols-2 gap-3 lg:grid-cols-4">
        {orderedDefs.map((def) => (
          <ReadingCard
            key={def.key}
            def={def}
            feed={feed[def.key]}
            allFeeds={feed}
            day={day}
            now={now}
            hero={def.key === heroKey}
            hinted={dropHint === def.key}
            dragging={dragKey === def.key}
            registerRef={registerRef}
            onPointerDown={handlePointerDown}
          />
        ))}
      </div>
    </GlassCard>
  )
}
