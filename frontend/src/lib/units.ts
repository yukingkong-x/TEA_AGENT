/**
 * 量纲唯一出口（contract 第 10 节已经把这件事钉死，之前工程里 0-1 与 0-100 混用过）：
 *
 * | 字段                        | 量纲      |
 * | --------------------------- | --------- |
 * | achievement / gap           | 0-100（%）|
 * | confidence                  | 0-100     |
 * | confidence_detail.*         | 0-1 原始分|
 *
 * 所以：主指标一律 `pct()`，三路原始分一律 `raw01()`（**不要 ×100**）。
 * 想把原始分合成总分，用 `weightedConfidence()`，它内部才做 ×100。
 */

export const CONFIDENCE_WEIGHTS = {
  data_quality: 0.5,
  rule_cross: 0.3,
  consistency: 0.2,
} as const

/** 置信度低于此值转人工（PRD 11.3，量纲 0-100） */
export const NEEDS_HUMAN_THRESHOLD = 60

/** 0-100 → "72.50%"；传 null/NaN 给「—」，绝不吐 NaN% */
export function pct(value?: number | null, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(digits)}%`
}

/** 0-1 原始分 → "0.50"；原样显示，不乘 100，不换算成百分比 */
export function raw01(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toFixed(2)
}

/** 湿度/读数一类的数值（也是 0-100 的百分数） */
export function humidity(value?: number | null, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(digits)}%`
}

export type ConfidenceDetail = {
  /** 0-1 */
  data_quality: number
  /** 0-1 */
  rule_cross: number
  /** 0-1 */
  consistency: number
  reasons?: string[]
}

/** 三路原始分加权 → 0-100，只用于对账，不要拿它替换后端给的 confidence */
export function weightedConfidence(detail: ConfidenceDetail): number {
  const { data_quality, rule_cross, consistency } = detail
  const score =
    data_quality * CONFIDENCE_WEIGHTS.data_quality +
    rule_cross * CONFIDENCE_WEIGHTS.rule_cross +
    consistency * CONFIDENCE_WEIGHTS.consistency
  return Math.round(score * 1000) / 10
}

/** 验证结论 → 徽章文案（needs_human 优先于达成率） */
export function verdictLabel(verdict: string): { text: string; className: string } {
  if (verdict === 'needs_human') return { text: '转人工', className: 'bg-[#F3E8FF] text-[#6D28D9]' }
  if (verdict === 'success') return { text: '闭环', className: 'bg-panel2 text-tea' }
  return { text: '未达标', className: 'bg-[#FFF4CC] text-[#8A6414]' }
}
