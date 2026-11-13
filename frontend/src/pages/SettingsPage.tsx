import { useState, type DragEvent } from 'react'
import { PageFrame } from '../components/PageFrame'
import { agents, devices } from '../data/snapshot'
import { useShell, type RunMode } from '../shell/ShellContext'

const prompts: Record<string, string> = {
  scout: '汇总环境与土壤读数。土壤湿度低于 40% 时发出预警，并请气象员、土壤师、植保员评估。',
  weather: '只根据天气工具的返回说话。拿不到数据就写数据不可用，不要编造降雨。',
  soil: '给墒情评级。低于 40% 为轻度缺水，建议灌溉，目标湿度 55%–65%。',
  pest: '先检索知识库。没有命中就写未检索到，不要凭空给农艺建议。',
  decision: '综合三方结论决定浇不浇。你不能直接给设备下指令。',
  executor: '只有你可以调用 send_device_cmd。下发后跟踪回执，超时按调度参数重试。',
  verifier: '用基线、复测和三路置信度出结论。达成率或置信度低于 60% 时不要宣称闭环。',
}

const profiles: Record<string, { role: string; temperature: string; permission: string; tools: string[] }> = {
  scout: { role: '数据汇总、异常初筛、发起巡园流程', temperature: '0.30', permission: '只读+报警', tools: ['get_env_status', 'get_soil_status', 'raise_alert'] },
  weather: { role: '天气与霜冻风险', temperature: '0.30', permission: '只读', tools: ['get_weather'] },
  soil: { role: '墒情分析与趋势', temperature: '0.30', permission: '只读', tools: ['get_soil_status'] },
  pest: { role: '病虫害与农艺风险，翻知识库', temperature: '0.40', permission: '只读（RAG）', tools: ['query_knowledge'] },
  decision: { role: '汇总情报拍板，生成任务', temperature: '0.20', permission: '只能创建任务', tools: ['create_task'] },
  executor: { role: '指令下发、盯回执、超时重试', temperature: '0.20', permission: '唯一可触硬件', tools: ['send_device_cmd', 'raise_alert'] },
  verifier: { role: '复测、算达成率、出报告、不达标启动修正', temperature: '0.30', permission: '裁判权', tools: ['verify_result', 'calc_achievement', 'write_report', 'create_task', 'raise_alert'] },
}

const faults = [
  { id: 'offline', label: '设备离线', hint: '设备静默，用来演示超时重试' },
  { id: 'ack_timeout', label: '回执超时', hint: '伪造回执超时，用来演示重试' },
  { id: 'dry_soil', label: '土壤干旱', hint: '湿度降到 25%，触发重度缺水' },
  { id: 'stuck_moisture', label: '湿度卡住', hint: '浇水后湿度不升，用来演示两轮对照' },
  { id: 'sensor_jitter', label: '读数抖动', hint: '读数上下跳 15%，用来演示转人工' },
]

const snippets = [
  { title: '茶园灌溉目标湿度', score: 0.86, text: '春茶期土壤湿度宜保持在 55%–65%，低于 40% 属于缺水，应补灌。' },
  { title: '渗透等待', score: 0.71, text: '浇水后等待约 90 秒再复测，避免表层水造成误判。' },
  { title: '分次灌溉', score: 0.64, text: '缺口大于 15 个百分点时，拆成两次浇水，间隔 60 秒。' },
]

type Doc = { id: string; name: string; status: string }

export function SettingsPage() {
  const { mode, setMode } = useShell()
  const [provider, setProvider] = useState('GLM-4-Flash')
  const [apiKey, setApiKey] = useState('')
  const [probe, setProbe] = useState('')
  const [promptMap, setPromptMap] = useState(prompts)
  const [enabled, setEnabled] = useState<Record<string, boolean>>(() => Object.fromEntries(agents.map((agent) => [agent.key, true])))
  const [openKey, setOpenKey] = useState<string | null>(null)
  const [deviceId, setDeviceId] = useState('k10-act-03')
  const [action, setAction] = useState('pump')
  const [duration, setDuration] = useState('30')
  const [ack, setAck] = useState('')
  const [activeFaults, setActiveFaults] = useState<string[]>([])
  const [parallel, setParallel] = useState(true)
  const [retries, setRetries] = useState(3)
  const [waitSeconds, setWaitSeconds] = useState(90)
  const [docs, setDocs] = useState<Doc[]>([{ id: 'doc-1', name: '茶园农艺手册.pdf', status: '已就绪' }])
  const [question, setQuestion] = useState('')
  const [hits, setHits] = useState<typeof snippets>([])

  function addDoc(name: string) {
    const id = `doc-${Date.now()}`
    setDocs((list) => [...list, { id, name, status: '处理中' }])
    window.setTimeout(() => {
      setDocs((list) => list.map((item) => (item.id === id ? { ...item, status: '已就绪' } : item)))
    }, 700)
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault()
    const file = event.dataTransfer.files[0]
    if (file) addDoc(file.name)
  }

  function search() {
    const text = question.trim()
    if (!text) {
      setHits([])
      return
    }
    const found = snippets.filter((item) => item.title.includes(text) || item.text.includes(text)).slice(0, 3)
    setHits(found)
  }

  return (
    <PageFrame title="设置">
      <div className="flex flex-col items-start">
        <section className="w-full px-5 py-5 text-left">
          <h2 className="text-paper">运行模式</h2>
          <p className="mt-1 text-sm leading-normal text-mute">切换后顶上的徽章跟着变。读数仍是写死的。</p>
          <div className="mt-4 flex justify-start gap-3" role="group" aria-label="运行模式">
            <ModeButton current={mode} value="mock" onPick={setMode} label="模拟" />
            <ModeButton current={mode} value="real" onPick={setMode} label="真机" />
          </div>
        </section>

        <section className="w-full border-t border-[#EEF0F3] px-5 py-5 text-left">
          <h2 className="text-paper">模型服务</h2>
          <div className="mt-4 grid gap-3">
            <label className="grid gap-1 text-base text-dim">
              服务商
              <select value={provider} onChange={(event) => setProvider(event.target.value)} className="h-11 rounded-btn border border-line bg-panel px-3 text-base text-paper">
                <option>GLM-4-Flash</option>
                <option>DeepSeek</option>
              </select>
            </label>
            <label className="grid gap-1 text-base text-dim">
              密钥
              <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} className="h-11 rounded-btn border border-line px-3 text-base text-paper" autoComplete="off" />
            </label>
            <div className="flex items-center justify-start gap-3">
              <button
                type="button"
                className="h-11 rounded-btn bg-tea px-4 text-base text-white hover:bg-teaHover active:bg-teaPress"
                onClick={() => setProbe(`${provider} · 128 ms`)}
              >
                测试连接
              </button>
              {probe ? <p className="num text-sm text-paper">{probe}</p> : null}
            </div>
          </div>
        </section>

        <section className="w-full border-t border-[#EEF0F3] px-5 py-5 text-left">
          <h2 className="text-paper">智能体</h2>
          <ul className="mt-4 grid gap-2">
            {agents.map((agent) => {
              const open = openKey === agent.key
              const profile = profiles[agent.key]
              return (
                <li key={agent.key} className="rounded-xl border border-line">
                  <button type="button" className="flex w-full items-center justify-start gap-3 px-3 py-3 text-left" onClick={() => setOpenKey(open ? null : agent.key)}>
                    <span className="text-lg" aria-hidden="true">{agent.avatar}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm text-paper">{agent.name}</span>
                      <span className="block truncate text-xs text-mute">{profile.tools.join('、')}</span>
                    </span>
                    <span className={`text-xs ${enabled[agent.key] ? 'text-tea' : 'text-mute'}`}>{enabled[agent.key] ? '启用' : '停用'}</span>
                  </button>
                  {open ? (
                    <div className="grid gap-3 border-t border-line px-3 py-3">
                      <div className="overflow-hidden rounded-xl border border-line bg-panel">
                        <table className="w-full border-collapse text-left text-sm leading-normal">
                          <tbody>
                            <tr>
                              <th className="w-24 border-b border-line bg-[#F7F8FA] px-4 py-3 text-left text-sm font-normal text-dim">身份</th>
                              <td className="border-b border-line px-4 py-3 text-paper">{agent.name}（{agent.key}）</td>
                            </tr>
                            <tr>
                              <th className="w-24 border-b border-line bg-[#F7F8FA] px-4 py-3 text-left text-sm font-normal text-dim">作用</th>
                              <td className="border-b border-line px-4 py-3 text-paper">{profile.role}</td>
                            </tr>
                            <tr>
                              <th className="w-24 border-b border-line bg-[#F7F8FA] px-4 py-3 text-left text-sm font-normal text-dim">模型</th>
                              <td className="border-b border-line px-4 py-3 text-paper">{provider}</td>
                            </tr>
                            <tr>
                              <th className="w-24 bg-[#F7F8FA] px-4 py-3 text-left align-top text-sm font-normal text-dim">提示词</th>
                              <td className="px-4 py-3">
                                <textarea
                                  value={promptMap[agent.key]}
                                  onChange={(event) => setPromptMap((current) => ({ ...current, [agent.key]: event.target.value }))}
                                  className="min-h-24 w-full resize-none border-0 bg-transparent p-0 text-sm leading-normal text-paper outline-none"
                                />
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                      <div className="overflow-hidden rounded-xl border border-line bg-panel">
                        <table className="w-full table-fixed border-collapse text-left text-sm leading-5">
                          <thead>
                            <tr className="bg-[#F7F8FA] text-dim">
                              <th className="px-3 py-1.5 text-left text-sm font-normal">工具</th>
                              <th className="w-28 px-3 py-1.5 text-left text-sm font-normal">温度</th>
                              <th className="w-40 px-3 py-1.5 text-left text-sm font-normal">权限</th>
                            </tr>
                          </thead>
                          <tbody>
                            {profile.tools.map((name) => (
                              <tr key={name} className="border-t border-line">
                                <td className="num px-3 py-1.5 align-middle text-paper">{name}</td>
                                <td className="num px-3 py-1.5 align-middle text-paper">{profile.temperature}</td>
                                <td className="px-3 py-1.5 align-middle text-paper">{profile.permission}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <label className="flex items-center gap-2 text-sm text-paper">
                        <input
                          type="checkbox"
                          className="accent-tea"
                          checked={enabled[agent.key]}
                          onChange={(event) => setEnabled((current) => ({ ...current, [agent.key]: event.target.checked }))}
                        />
                        启用这个智能体
                      </label>
                    </div>
                  ) : null}
                </li>
              )
            })}
          </ul>
        </section>

        <section className="w-full border-t border-[#EEF0F3] px-5 py-5 text-left">
          <h2 className="text-paper">设备调试</h2>
          <div className="mt-4 grid gap-3">
            <label className="grid gap-1 text-base text-dim">
              设备
              <select value={deviceId} onChange={(event) => setDeviceId(event.target.value)} className="h-11 rounded-btn border border-line bg-panel px-3 text-base text-paper">
                {devices.map((device) => (
                  <option key={device.id} value={device.id}>
                    {device.name} · {device.id}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-base text-dim">
              动作
              <select value={action} onChange={(event) => setAction(event.target.value)} className="h-11 rounded-btn border border-line bg-panel px-3 text-base text-paper">
                <option value="pump">pump</option>
                <option value="read_now">read_now</option>
              </select>
            </label>
            <label className="grid gap-1 text-base text-dim">
              时长（秒）
              <input value={duration} onChange={(event) => setDuration(event.target.value)} className="num h-11 rounded-btn border border-line px-3 text-base text-paper" />
            </label>
            <button
              type="button"
              className="h-11 w-fit rounded-btn bg-tea px-4 text-base text-white hover:bg-teaHover active:bg-teaPress"
              onClick={() =>
                setAck(
                  JSON.stringify(
                    { device_id: deviceId, action, params: { duration_s: Number(duration) || 0 }, status: 'received', ack: 'done' },
                    null,
                    2,
                  ),
                )
              }
            >
              发送
            </button>
            {ack ? <pre className="num overflow-auto rounded-xl bg-[#F7F8FA] p-3 text-xs leading-normal text-dim">{ack}</pre> : null}
          </div>
        </section>

        {mode === 'mock' ? (
          <section className="w-full border-t border-[#EEF0F3] px-5 py-5 text-left">
            <h2 className="text-paper">故障注入</h2>
            <p className="mt-1 text-sm leading-normal text-mute">只在模拟模式出现。点一下记一笔，不会真的改设备。</p>
            <div className="mt-4 flex flex-wrap justify-start gap-3">
              {faults.map((fault) => {
                const on = activeFaults.includes(fault.id)
                return (
                  <button
                    key={fault.id}
                    type="button"
                    aria-pressed={on}
                    title={fault.hint}
                    onClick={() => setActiveFaults((list) => (list.includes(fault.id) ? list.filter((id) => id !== fault.id) : [...list, fault.id]))}
                    className={`h-11 rounded-btn border px-4 text-base ${on ? 'border-tea bg-tea text-white' : 'border-line text-paper hover:border-tea hover:text-tea'}`}
                  >
                    {fault.label}
                  </button>
                )
              })}
            </div>
          </section>
        ) : null}

        <section className="w-full border-t border-[#EEF0F3] px-5 py-5 text-left">
          <h2 className="text-paper">调度参数</h2>
          <div className="mt-4 grid gap-4">
            <label className="flex items-center gap-2 text-base text-paper">
              <input type="checkbox" className="accent-tea" checked={parallel} onChange={(event) => setParallel(event.target.checked)} />
              并行会诊
            </label>
            <label className="grid gap-1 text-base text-dim">
              最多重试
              <input type="number" min={0} max={3} value={retries} onChange={(event) => setRetries(Number(event.target.value))} className="num h-11 rounded-btn border border-line px-3 text-base text-paper" />
            </label>
            <label className="grid gap-1 text-base text-dim">
              渗透等待（秒）
              <input type="number" min={0} value={waitSeconds} onChange={(event) => setWaitSeconds(Number(event.target.value))} className="num h-11 rounded-btn border border-line px-3 text-base text-paper" />
            </label>
          </div>
        </section>

        <section className="w-full border-t border-[#EEF0F3] px-5 py-5 text-left">
          <h2 className="text-paper">知识库</h2>
          <label
            className="mt-4 grid h-28 cursor-pointer place-items-center rounded-xl border border-dashed border-line bg-[#F7F8FA] text-sm text-mute"
            onDragOver={(event) => event.preventDefault()}
            onDrop={onDrop}
          >
            把文档拖到这里，或点此选择
            <input
              type="file"
              accept=".pdf,.txt,.md"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) addDoc(file.name)
                event.target.value = ''
              }}
            />
          </label>
          <ul className="mt-3 grid gap-2">
            {docs.map((doc) => (
              <li key={doc.id} className="flex items-center justify-between gap-3 text-sm">
                <span className="text-paper">{doc.name}</span>
                <span className={doc.status === '已就绪' ? 'text-tea' : 'text-mute'}>{doc.status}</span>
              </li>
            ))}
          </ul>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="输入问题，例如 缺水"
              className="h-11 min-w-0 flex-1 rounded-btn border border-line px-3 text-base text-paper"
            />
            <button type="button" className="h-11 rounded-btn bg-tea px-4 text-base text-white hover:bg-teaHover active:bg-teaPress" onClick={search}>
              检索
            </button>
          </div>
          {question.trim() && hits.length === 0 ? <p className="mt-3 text-sm text-mute">未检索到相关内容。</p> : null}
          <ul className="mt-3 grid gap-2">
            {hits.map((hit) => (
              <li key={hit.title} className="rounded-xl bg-[#F7F8FA] px-3 py-3">
                <p className="text-sm text-paper">
                  {hit.title} <span className="num text-mute">{hit.score.toFixed(2)}</span>
                </p>
                <p className="mt-1 text-sm leading-normal text-dim">{hit.text}</p>
              </li>
            ))}
          </ul>
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
      className={`h-11 rounded-btn border px-6 text-base ${active ? 'border-tea bg-tea text-white' : 'border-line text-paper hover:border-tea hover:text-tea'}`}
    >
      {label}
    </button>
  )
}
