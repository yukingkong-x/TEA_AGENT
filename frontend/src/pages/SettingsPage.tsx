import { PageFrame } from '../components/PageFrame'
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
    <PageFrame title="设置">
    <div className="grid items-start lg:grid-cols-[280px_minmax(0,1fr)]">
        <section className="border-b border-[#EEF0F3] p-5 lg:border-b-0 lg:border-r">
          <h2 className="text-paper">运行模式</h2>
          <p className="mt-1 text-sm leading-normal text-mute">切换后顶上的徽章跟着变。读数仍是写死的。</p>
          <div className="mt-4 grid grid-cols-2 gap-3" role="group" aria-label="运行模式">
            <ModeButton current={mode} value="mock" onPick={setMode} label="模拟" />
            <ModeButton current={mode} value="real" onPick={setMode} label="真机" />
          </div>
        </section>
        <section>
          <h2 className="border-b border-[#EEF0F3] px-5 py-4 text-paper">当前参数</h2>
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
    </PageFrame>
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
      className={`h-11 rounded-btn border text-base ${active ? 'border-tea bg-tea text-white' : 'border-line text-paper hover:border-tea hover:text-tea'}`}
    >
      {label}
    </button>
  )
}
