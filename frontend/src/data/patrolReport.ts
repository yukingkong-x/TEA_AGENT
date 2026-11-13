const LOW = 55

function achievement(baseline: number, measured: number) {
  if (measured >= LOW) return 100
  if (measured <= baseline) return 0
  return ((measured - baseline) / (LOW - baseline)) * 100
}

export type PatrolRound = {
  round: number
  baseline: number
  measured: number
  rate: number
  confidence: number
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
    confidence: 100,
    diagnosis: '缺口 10.0%，达成率低于 60%。',
    correction: `补灌 ${10 + gap} 秒`,
  },
  {
    round: 2,
    baseline: round1Measured,
    measured: round2Measured,
    rate: achievement(round1Measured, round2Measured),
    confidence: 100,
    diagnosis: '落在目标 55%–65%。',
    correction: '不必再浇',
  },
]

const jitterMeasured = 45

export type PatrolRun = {
  id: string
  name: string
  outcome: string
  rounds: PatrolRound[]
}

export const patrolRuns: PatrolRun[] = [
  {
    id: 'run-1001',
    name: '模拟巡园 · A区茶垄',
    outcome: '闭环成功',
    rounds: patrolRounds,
  },
  {
    id: 'run-1002',
    name: '读数抖动 · 转人工',
    outcome: '转人工',
    rounds: [
      {
        round: 1,
        baseline: round1Baseline,
        measured: jitterMeasured,
        rate: achievement(round1Baseline, jitterMeasured),
        confidence: 50,
        diagnosis: '三次读数极差超过 5%，置信度低于 60%。',
        correction: '暂停闭环，转人工',
      },
    ],
  },
]

export function dailyMarkdown(run: PatrolRun) {
  const lines = [`# ${run.name}`, '', '## 证据链', '']
  for (const round of run.rounds) {
    lines.push(
      `- 第 ${round.round} 轮：基线 ${round.baseline.toFixed(1)}% → 复测 ${round.measured.toFixed(1)}%，达成率 ${round.rate.toFixed(2)}%，置信度 ${round.confidence.toFixed(2)}%。诊断：${round.diagnosis}修正：${round.correction}`,
    )
  }
  lines.push('', '## 结论', '', run.outcome === '闭环成功' ? '达成率与置信度均不低于 60%，闭环成功。' : '置信度低于 60%，本轮挂起，转人工。')
  return lines.join('\n')
}
