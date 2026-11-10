import { GardenPhoto } from '../components/GardenPhoto'

export function ReportPage() {
  return (
    <div className="page-enter mx-auto flex w-full max-w-[1360px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[28px] font-medium leading-tight">验证报告</h1>
          <p className="mt-2 text-base text-dim">还没有完成的巡园。</p>
        </div>
        <button type="button" className="btn btn-ghost" disabled>
          生成日报
        </button>
      </header>
      <GardenPhoto src="/garden/ridge.svg" label="一层层的茶山" />
      <section className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="flex flex-col items-center justify-center rounded-card border border-line bg-panel px-6 py-10">
          <p className="text-[13px] text-dim">达成率</p>
          <p className="num mt-3 text-5xl text-paper">—</p>
          <p className="mt-6 text-[13px] text-dim">置信度 —</p>
        </div>
        <div className="overflow-x-auto rounded-card border border-line">
          <table className="w-full min-w-[640px] border-collapse text-left text-sm">
            <thead className="bg-panel text-dim">
              <tr>
                {['轮次', '基线', '复测', '达成率', '诊断', '修正'].map((column) => (
                  <th key={column} className="px-4 py-3 font-medium">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="bg-ink">
              <tr>
                <td colSpan={6} className="px-4 py-16 text-center text-base text-dim">
                  两轮对照会在浇水复测之后出现。
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
