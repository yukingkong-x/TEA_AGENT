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
    diagnosis: '复测 45.0%，缺口 10.0%，达成率低于 60%。',
    correction: `补灌 ${10 + gap} 秒`,
  },
  {
    round: 2,
    baseline: round1Measured,
    measured: round2Measured,
    rate: achievement(round1Measured, round2Measured),
    diagnosis: '复测 57.0%，落在目标 55%–65%。',
    correction: '不必再浇',
  },
]

export const patrolReport = {
  name: '模拟巡园 · A区茶垄',
}
