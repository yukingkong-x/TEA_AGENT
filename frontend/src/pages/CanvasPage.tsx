import { useLocation } from 'react-router-dom'
import { GardenPhoto } from '../components/GardenPhoto'
import { consultNodes, flowNodes } from '../data/snapshot'

export function CanvasPage() {
  const location = useLocation()
  const armed = Boolean((location.state as { armed?: boolean } | null)?.armed)

  return (
    <div className="page-enter mx-auto flex w-full max-w-[1360px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[28px] font-medium leading-tight">巡园浇水</h1>
          <p className="mt-2 text-base text-dim">默认工作流。节点按巡园、会诊、决策排开。</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm text-dim">
          <span className="num rounded-btn border border-line bg-panel px-3 py-2">00:00</span>
          <span className="rounded-btn border border-line bg-panel px-3 py-2">{armed ? '第 1 轮' : '未开始'}</span>
        </div>
      </header>
      <GardenPhoto src="/garden/path.svg" label="茶垄间的小路" />
      <section className="rounded-card border border-line bg-panel p-5">
        <ol className="grid gap-3 lg:grid-cols-6">
          {flowNodes.map((node, index) => (
            <li key={node.id} className="min-w-0">
              <div
                className={`flex h-full min-h-[92px] flex-col justify-between rounded-card border px-3 py-3 ${
                  armed && node.id === 'n1' ? 'border-tea bg-ink' : 'border-line bg-ink'
                }`}
              >
                <span className="text-[13px] text-dim">
                  {index + 1}. {node.kind}
                </span>
                <span className="mt-3 text-base text-paper">{node.name}</span>
              </div>
            </li>
          ))}
        </ol>
        <div className="mt-4 rounded-card border border-dashed border-line p-4">
          <h2 className="text-[13px] font-medium text-dim">三方会诊</h2>
          <ul className="mt-3 grid gap-3 sm:grid-cols-3">
            {consultNodes.map((node) => (
              <li key={node.id} className="rounded-btn border border-line bg-ink px-3 py-3 text-base">
                {node.name}
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  )
}
