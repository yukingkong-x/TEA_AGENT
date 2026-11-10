import { GardenPhoto } from '../components/GardenPhoto'
import { useShell, type RunMode } from '../shell/ShellContext'

const rows = [
  { label: '模型', value: 'GLM-4-Flash' },
  { label: '并行会诊', value: '开' },
  { label: '最多重试', value: '3 次' },
  { label: '渗透等待', value: '90 秒' },
]

export function SettingsPage() {
  const { mode, setMode } = useShell()

  return (
    <div className="page-enter mx-auto flex w-full max-w-[760px] flex-col gap-4">
      <header>
        <h1 className="text-[28px] font-medium leading-tight">设置</h1>
        <p className="mt-2 text-base text-dim">切换模拟或真机，顶栏徽章跟着变。读数仍是这一版写死的数据。</p>
      </header>
      <GardenPhoto src="/garden/morning.svg" label="清晨的茶园" />
      <section className="rounded-card border border-line bg-panel p-5">
        <h2 className="text-base font-medium">运行模式</h2>
        <div className="mt-4 grid grid-cols-2 gap-3" role="group" aria-label="运行模式">
          <ModeButton current={mode} value="mock" onPick={setMode} label="模拟" />
          <ModeButton current={mode} value="real" onPick={setMode} label="真机" />
        </div>
      </section>
      <section className="rounded-card border border-line bg-panel">
        <h2 className="border-b border-line px-5 py-4 text-base font-medium">当前参数</h2>
        <dl>
          {rows.map((row) => (
            <div key={row.label} className="flex items-center justify-between gap-4 border-b border-line px-5 py-4 last:border-b-0">
              <dt className="text-sm text-dim">{row.label}</dt>
              <dd className="num text-sm text-paper">{row.value}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  )
}

function ModeButton({
  current,
  value,
  label,
  onPick,
}: {
  current: RunMode
  value: RunMode
  label: string
  onPick: (mode: RunMode) => void
}) {
  const active = current === value
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => onPick(value)}
      className={`h-11 rounded-btn border text-base ${active ? 'border-tea bg-tea text-ink' : 'border-line text-paper'}`}
    >
      {label}
    </button>
  )
}
