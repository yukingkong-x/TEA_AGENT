import { ReportTrend } from '../components/ReportTrend'
import { patrolReport, patrolRounds, type PatrolRound } from '../data/patrolReport'

function RoundCard({ round }: { round: PatrolRound }) {
  const radius = 46
  const center = 60
  const length = 2 * Math.PI * radius
  const turn = `rotate(-90 ${center} ${center})`
  const closed = round.rate >= 60

  return (
    <section className="rounded-[22px] bg-panel px-5 py-5 shadow-[0_10px_28px_rgba(20,40,30,0.06)]">
      <h2 className="text-[15px] font-medium text-paper">第 {round.round} 轮</h2>
      <div className="mt-4 flex items-center gap-6">
        <div className="w-[148px] shrink-0">
          <div className="relative h-[148px] w-[148px]">
            <svg viewBox="0 0 120 120" className="h-full w-full" aria-hidden="true">
              <circle cx={center} cy={center} r={radius} fill="none" stroke="#E7EEE9" strokeWidth="12" />
              <circle
                cx={center}
                cy={center}
                r={radius}
                fill="none"
                stroke="#E4B423"
                strokeWidth="12"
                strokeDasharray={`${length * (round.measured / 100)} ${length}`}
                transform={turn}
              />
              <circle
                cx={center}
                cy={center}
                r={radius}
                fill="none"
                stroke="#1F7A45"
                strokeWidth="12"
                strokeDasharray={`${length * (round.baseline / 100)} ${length}`}
                transform={turn}
              />
            </svg>
            <div className="absolute inset-0 grid place-items-center">
              <p className="text-center">
                <span className="num block text-[22px] font-bold leading-none text-paper">{round.rate.toFixed(2)}%</span>
                <span className="mt-1 block text-[12px] text-dim">达成率</span>
              </p>
            </div>
          </div>
          <ul className="mt-3 grid gap-1.5 text-[13px] text-paper">
            <li className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-[#1F7A45]" aria-hidden="true" />
              基线 {round.baseline.toFixed(1)}%
            </li>
            <li className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-[#E4B423]" aria-hidden="true" />
              复测 {round.measured.toFixed(1)}%
            </li>
          </ul>
        </div>
        <dl className="grid min-w-0 flex-1 gap-3 text-sm">
          <div className="flex gap-3">
            <dt className="w-10 shrink-0 text-dim">诊断</dt>
            <dd className="text-paper">{round.diagnosis}</dd>
          </div>
          <div className="flex gap-3">
            <dt className="w-10 shrink-0 text-dim">修正</dt>
            <dd className="text-paper">{round.correction}</dd>
          </div>
          <div className="flex gap-3">
            <dt className="w-10 shrink-0 text-dim">结果</dt>
            <dd>
              <span className={`inline-flex h-7 items-center rounded-btn px-2 text-[13px] ${closed ? 'bg-panel2 text-tea' : 'bg-[#FFF4CC] text-[#8A6414]'}`}>
                {closed ? '闭环' : '未达标'}
              </span>
            </dd>
          </div>
        </dl>
      </div>
    </section>
  )
}

export function ReportPage() {
  const second = patrolRounds[1]

  return (
    <div className="page-enter -mt-3 mx-auto flex w-full max-w-[1360px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[28px] font-medium leading-none">验证报告</h1>
          <p className="mt-2 text-sm text-dim">{patrolReport.name}。第 2 轮复测 {second.measured.toFixed(1)}%。</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => window.print()}>
          生成日报
        </button>
      </header>
      <div className="grid gap-4 lg:grid-cols-2">
        {patrolRounds.map((round) => (
          <RoundCard key={round.round} round={round} />
        ))}
      </div>
      <section className="rounded-card border border-line bg-panel px-5 py-4">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-base font-medium">湿度轨迹</h2>
          <p className="text-sm text-dim">两轮复测</p>
        </div>
        <ReportTrend />
      </section>
    </div>
  )
}
