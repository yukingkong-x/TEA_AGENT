import type { ConfidenceDetail } from '../lib/units'

const LOW = 55

function achievement(baseline: number, measured: number) {
  if (measured >= LOW) return 100
  if (measured <= baseline) return 0
  return ((measured - baseline) / (LOW - baseline)) * 100
}

/**
 * run 的结论（contract：`outcome` 直接来自验证记录，不是 run.status）。
 * 后端 `app/verification/report.py` 的 VERDICT_LABEL 是唯一文案来源，这里逐字对齐。
 */
export type RunOutcome = 'success' | 'failed' | 'needs_human' | 'running' | 'pending' | 'unverified'

export const OUTCOME_LABEL: Record<RunOutcome, string> = {
  success: '✅ 闭环成功',
  failed: '🔄 未达标，已触发修正',
  needs_human: '🚨 转人工',
  running: '⏳ 执行中',
  pending: '⏸ 未开始',
  // run 跑完但验证官没出结论：流程走完 ≠ 达标，不能显示成「闭环成功」
  unverified: '⚠️ 未产生验证结果',
}

export function outcomeLabel(outcome: string) {
  return OUTCOME_LABEL[outcome as RunOutcome] ?? outcome
}

export type PatrolRound = {
  round: number
  /** 可能为 null（基线缺失）：显示「—」，不要 ?? 0 */
  baseline: number | null
  measured: number
  /** 达成率，0-100（%） */
  rate: number
  /** 置信度，0-100；60 是转人工阈值（后端 rounds[].confidence 是 0-1，适配层已 ×100） */
  confidence: number
  /** 基线缺失时 achievement 是「算不出来」，不是 0% */
  baselineMissing?: boolean
  /** 本轮浇水时长，秒。后端从被验证任务的 payload.duration_s 回查，是**真值**；0/缺省 = 没记录 */
  durationS?: number
  /** 三路原始分，0-1（contract 第 10 节），只用于展示构成，别当百分比 */
  detail: ConfidenceDetail
  diagnosis: string
  correction: string
}

const round1Measured = 45
const round2Measured = 57
const round1Baseline = 38.5
const gap = LOW - round1Measured

export const patrolRounds: PatrolRound[] = [
  {
    round: 1,
    baseline: round1Baseline,
    measured: round1Measured,
    rate: achievement(round1Baseline, round1Measured),
    // 三路原始分加权 1.0*0.5 + 1.0*0.3 + 0.5*0.2 = 0.90 → 90.0
    confidence: 90,
    durationS: 45,
    detail: {
      data_quality: 1,
      rule_cross: 1,
      consistency: 0.5,
      reasons: ['复测读数偏低 12.3%，与近 24h 均值偏差 2.4σ'],
    },
    diagnosis: '缺口 10.0%，达成率低于 60%。',
    correction: `补灌 ${10 + gap} 秒`,
  },
  {
    round: 2,
    baseline: round1Measured,
    measured: round2Measured,
    rate: achievement(round1Measured, round2Measured),
    confidence: 100,
    durationS: 20,
    detail: { data_quality: 1, rule_cross: 1, consistency: 1 },
    diagnosis: '落在目标 55%–65%。',
    correction: '不必再浇',
  },
]

const jitterMeasured = 45

export type PatrolRun = {
  id: string
  name: string
  /** 六态之一，见 RunOutcome；不要自己编「闭环成功」 */
  outcome: RunOutcome
  rounds: PatrolRound[]
}

export const patrolRuns: PatrolRun[] = [
  {
    id: 'run-1001',
    name: '模拟巡园 · A区茶垄',
    outcome: 'success',
    rounds: patrolRounds,
  },
  {
    id: 'run-1002',
    name: '读数抖动 · 转人工',
    outcome: 'needs_human',
    rounds: [
      {
        round: 1,
        baseline: round1Baseline,
        measured: jitterMeasured,
        rate: achievement(round1Baseline, jitterMeasured),
        confidence: 50,
        durationS: 45,
        detail: {
          data_quality: 0.4,
          rule_cross: 1,
          consistency: 0.2,
          reasons: ['三次读数极差超过 5%', '与近 24h 均值偏差 3.1σ'],
        },
        diagnosis: '三次读数极差超过 5%，置信度低于 60%。',
        correction: '暂停闭环，转人工',
      },
    ],
  },
  {
    id: 'run-1003',
    name: '跑完未验证 · 设备离线',
    // run 结束态是 success，但验证官没留下记录 → unverified，绝不写「闭环成功」
    outcome: 'unverified',
    rounds: [],
  },
]

/** 基线缺失 / 基线为 null 时达成率「算不出来」，不能写成 0% */
export function formatAchievement(round: PatrolRound) {
  if (round.baselineMissing || round.baseline === null) return '算不出来（基线缺失）'
  if (!Number.isFinite(round.rate)) return '—'
  return `${round.rate.toFixed(2)}%`
}

/** 浇水时长（秒）→ 人话。0 / 缺省 = 后端没查到，显示「—」，不要写成 0 秒 */
export function formatDuration(round: PatrolRound) {
  const seconds = round.durationS
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds <= 0) return '—'
  if (seconds < 60) return `${Math.round(seconds)} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`
}

/** 结论段的人话：unverified 必须点明「没判定」，不能含糊成「已完成」 */
export function outcomeSummary(run: PatrolRun) {
  switch (run.outcome) {
    case 'success':
      return '达成率与置信度均不低于 60%，闭环成功。'
    case 'failed':
      return '达成率低于 60%，已触发修正任务（Self-Loop）。'
    case 'needs_human':
      return '置信度低于 60%，本轮挂起，转人工。'
    case 'unverified':
      return '本次运行没有产生验证记录，无法判定是否达标——流程跑通不等于浇水达标，不能算作一次成功的闭环。'
    case 'running':
      return '运行中，尚未产生结论。'
    case 'pending':
      return '尚未开始。'
    default:
      return run.outcome
  }
}

export function dailyMarkdown(run: PatrolRun) {
  const lines = [`# ${run.name}`, '', `> 结论：**${outcomeLabel(run.outcome)}**`, '', '## 证据链', '']
  if (run.rounds.length === 0) {
    lines.push(outcomeSummary(run))
  }
  for (const round of run.rounds) {
    const baseline = round.baseline === null ? '—' : `${round.baseline.toFixed(1)}%`
    lines.push(
      `- 第 ${round.round} 轮：浇水 ${formatDuration(round)}，基线 ${baseline} → 复测 ${round.measured.toFixed(1)}%，达成率 ${formatAchievement(round)}，置信度 ${round.confidence.toFixed(2)}%。诊断：${round.diagnosis}修正：${round.correction}`,
    )
  }
  lines.push('', '## 结论', '', outcomeSummary(run))
  return lines.join('\n')
}
