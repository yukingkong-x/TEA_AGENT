import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { PageFrame } from '../components/PageFrame'
import { ApiError } from '../api/client'
import { endpoints } from '../api/endpoints'
import type { AgentDto, DeviceDto, KnowledgeDocDto, KnowledgeHitDto, MockStateDto, SettingsDto } from '../api/types'
import { agents as localAgents } from '../data/snapshot'
import { useShell, type RunMode } from '../shell/ShellContext'

/** 后端 agents 表为空时的展示兜底：本地样例没有数据库 id，用负数避开真实主键 */
function sampleAgents(): AgentDto[] {
  return localAgents.map((agent, index) => ({
    id: -(index + 1),
    agent_key: agent.key,
    name: agent.name,
    avatar: agent.avatar,
    system_prompt: SAMPLE_PROMPTS[agent.key] ?? '',
    tools_json: SAMPLE_TOOLS[agent.key] ?? [],
    model: 'glm',
    temperature: 0.3,
    enabled: true,
    updated_at: null,
  }))
}

const SAMPLE_PROMPTS: Record<string, string> = {
  scout: '汇总环境与土壤读数。土壤湿度低于 40% 时发出预警，并请气象员、土壤师、植保员评估。',
  weather: '只根据天气工具的返回说话。拿不到数据就写数据不可用，不要编造降雨。',
  soil: '给墒情评级。低于 40% 为轻度缺水，建议灌溉，目标湿度 55%–65%。',
  pest: '先检索知识库。没有命中就写未检索到，不要凭空给农艺建议。',
  decision: '综合三方结论决定浇不浇。你不能直接给设备下指令。',
  executor: '只有你可以调用 send_device_cmd。下发后跟踪回执，超时按调度参数重试。',
  verifier: '用基线、复测和三路置信度出结论。达成率或置信度低于 60% 时不要宣称闭环。',
}

const SAMPLE_TOOLS: Record<string, string[]> = {
  scout: ['get_env_status', 'get_soil_status', 'raise_alert'],
  weather: ['get_weather'],
  soil: ['get_soil_status'],
  pest: ['query_knowledge'],
  decision: ['create_task'],
  executor: ['send_device_cmd', 'raise_alert'],
  verifier: ['verify_result', 'calc_achievement', 'write_report', 'create_task', 'raise_alert'],
}

/** PRD 12.2 五种故障，id 与后端 FAULT_NAMES 逐字对齐 */
const faults = [
  { id: 'offline', label: '设备离线', hint: '设备静默，用来演示超时重试' },
  { id: 'ack_timeout', label: '回执超时', hint: '伪造回执超时，用来演示重试' },
  { id: 'dry_soil', label: '土壤干旱', hint: '湿度降到 25%，触发重度缺水' },
  { id: 'stuck_moisture', label: '湿度卡住', hint: '浇水后湿度不升，用来演示两轮对照' },
  { id: 'sensor_jitter', label: '读数抖动', hint: '读数上下跳 15%，用来演示转人工' },
] as const

const weathers = [
  { id: 'sunny', label: '晴' },
  { id: 'cloudy', label: '多云' },
  { id: 'rainy', label: '雨' },
  { id: 'frost', label: '霜冻' },
] as const

const DEVICE_ACTIONS = ['pump', 'read_now', 'relay_off', 'calibrate_dry', 'calibrate_wet', 'reboot'] as const

function errText(err: unknown) {
  if (err instanceof ApiError) return err.notReady ? '模块接入中（SEAM_NOT_READY）' : err.message
  return err instanceof Error ? err.message : String(err)
}

/** 设置项快照：GET 回来是 [{key,value,description}]，取用统一走这里 */
function useItems(settings: SettingsDto | null) {
  return useMemo(() => {
    const map = new Map<string, unknown>()
    for (const item of settings?.items ?? []) map.set(item.key, item.value)
    return map
  }, [settings])
}

const asBool = (value: unknown, fallback = false) => (typeof value === 'boolean' ? value : fallback)
const asNum = (value: unknown, fallback = 0) => (typeof value === 'number' ? value : fallback)
const asStr = (value: unknown, fallback = '') => (typeof value === 'string' ? value : fallback)
function asPair(value: unknown, fallback: [number, number]): [number, number] {
  if (Array.isArray(value) && value.length === 2 && value.every((n) => typeof n === 'number')) {
    return [value[0] as number, value[1] as number]
  }
  return fallback
}

type Doc = KnowledgeDocDto

export function SettingsPage() {
  const { mode, setMode, lastError: modeError, live } = useShell()

  const [settings, setSettings] = useState<SettingsDto | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saveNote, setSaveNote] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const items = useItems(settings)

  const [provider, setProvider] = useState<'glm' | 'deepseek'>('glm')
  const [apiKey, setApiKey] = useState('')
  const [probe, setProbe] = useState('')

  const [agents, setAgents] = useState<AgentDto[]>([])
  /** true = agents 表是空的，现在展示的是本地样例，改动落不了库 */
  const [agentsSample, setAgentsSample] = useState(false)
  const [promptDraft, setPromptDraft] = useState<Record<string, string>>({})
  const [openKey, setOpenKey] = useState<string | null>(null)

  const [devices, setDevices] = useState<DeviceDto[]>([])
  const [deviceId, setDeviceId] = useState('')
  const [action, setAction] = useState<string>('pump')
  const [duration, setDuration] = useState('30')
  const [ack, setAck] = useState('')
  const [cmdBusy, setCmdBusy] = useState(false)

  const [mock, setMock] = useState<MockStateDto | null>(null)
  const [faultNote, setFaultNote] = useState<string | null>(null)

  const [parallel, setParallel] = useState(true)
  const [retries, setRetries] = useState(3)
  const [range, setRange] = useState<[number, number]>([55, 65])
  const [cron, setCron] = useState('0 */2 * * *')

  const [docs, setDocs] = useState<Doc[]>([])
  const [question, setQuestion] = useState('')
  const [hits, setHits] = useState<KnowledgeHitDto[] | null>(null)
  const [searchNote, setSearchNote] = useState<string | null>(null)
  const [uploadBusy, setUploadBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  /** 只有用户真正改过的字段才进 values；GET 回来的密钥是掩码，回传会把掩码当明文落库 */
  const saveValues = useCallback(async (values: Record<string, unknown>) => {
    if (!Object.keys(values).length) return
    setSaving(true)
    setSaveNote(null)
    try {
      const next = await endpoints.updateSettings(values)
      setSettings(next)
      setSaveNote(`已写入后端：${Object.keys(values).join('、')}`)
      setLoadError(null)
    } catch (err) {
      setSaveNote(`保存失败：${errText(err)}`)
    } finally {
      setSaving(false)
    }
  }, [])

  const load = useCallback(async () => {
    try {
      const [nextSettings, agentList, deviceList, mockState, docList] = await Promise.all([
        endpoints.settings(),
        endpoints.agents(),
        endpoints.devices(),
        endpoints.mockState(),
        endpoints.knowledgeDocs(),
      ])
      setSettings(nextSettings)
      // 队长的 agents 表在引擎仓库里，队员B 的库目前是空的：
      // 返回空数组时退到本地样例（七个角色），但要在页面上说清楚改动落不了库
      const useSample = agentList.length === 0
      setAgentsSample(useSample)
      setAgents(useSample ? sampleAgents() : agentList)
      setPromptDraft(
        Object.fromEntries(
          (useSample ? sampleAgents() : agentList).map((item) => [item.agent_key, item.system_prompt ?? '']),
        ),
      )
      setDevices(deviceList)
      setDeviceId((current) => current || deviceList[0]?.device_id || '')
      setMock(mockState)
      setDocs(docList)
      setLoadError(null)
    } catch (err) {
      setLoadError(errText(err))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // 设置项落地到本地控件状态（只在拿到新快照时刷，用户正在编辑的字段不覆盖）
  useEffect(() => {
    if (!settings) return
    setProvider(asStr(items.get('llm_provider'), 'glm') === 'deepseek' ? 'deepseek' : 'glm')
    setParallel(asBool(items.get('parallel_enabled'), true))
    setRetries(asNum(items.get('max_retries'), 3))
    setRange(asPair(items.get('irrigation_default_range'), [55, 65]))
    setCron(asStr(items.get('schedule_cron'), '0 */2 * * *'))
  }, [settings, items])

  async function probeModel() {
    try {
      const health = await endpoints.health()
      setProbe(
        `${health.llm_ready ? 'LLM 就绪' : 'LLM 未就绪'} · ${health.mode === 'mock' ? '模拟' : '真机'} · v${health.version}`,
      )
    } catch (err) {
      setProbe(errText(err))
    }
  }

  async function toggleAgent(agent: AgentDto, enabled: boolean) {
    setAgents((list) => list.map((item) => (item.agent_key === agent.agent_key ? { ...item, enabled } : item)))
    if (agentsSample) {
      setSaveNote('本地样例智能体，开关只改显示；后端 agents 表是空的。')
      return
    }
    try {
      const updated = await endpoints.updateAgent(agent.agent_key, { enabled })
      setAgents((list) => list.map((item) => (item.agent_key === updated.agent_key ? updated : item)))
    } catch (err) {
      setAgents((list) => list.map((item) => (item.agent_key === agent.agent_key ? { ...item, enabled: !enabled } : item)))
      setSaveNote(`智能体开关失败：${errText(err)}`)
    }
  }

  async function savePrompt(agent: AgentDto) {
    const text = promptDraft[agent.agent_key] ?? ''
    if (agentsSample) {
      setSaveNote('本地样例智能体，提示词只改显示；后端 agents 表是空的。')
      return
    }
    try {
      const updated = await endpoints.updateAgent(agent.agent_key, { system_prompt: text })
      setAgents((list) => list.map((item) => (item.agent_key === updated.agent_key ? updated : item)))
      setSaveNote(`「${updated.name}」提示词已保存`)
    } catch (err) {
      setSaveNote(`提示词保存失败：${errText(err)}`)
    }
  }

  async function sendCmd() {
    if (!deviceId) return
    setCmdBusy(true)
    setAck('')
    try {
      const result = await endpoints.deviceCmd(deviceId, {
        action,
        params: action === 'pump' ? { duration_s: Number(duration) || 0 } : {},
      })
      setAck(JSON.stringify(result, null, 2))
    } catch (err) {
      setAck(JSON.stringify({ error: errText(err) }, null, 2))
    } finally {
      setCmdBusy(false)
    }
  }

  async function toggleFault(id: string) {
    const on = faultActive(mock, id)
    try {
      const next = on ? await endpoints.clearFault(id) : await endpoints.injectFault({ fault: id, seconds: 120 })
      setMock({ ...(mock ?? {}), ...next })
      setFaultNote(on ? `已清除「${id}」` : `已注入「${id}」（120s）`)
    } catch (err) {
      setFaultNote(`故障注入失败：${errText(err)}`)
    }
  }

  async function switchWeather(id: 'sunny' | 'cloudy' | 'rainy' | 'frost') {
    try {
      const next = await endpoints.weather(id)
      setMock({ ...(mock ?? {}), ...next })
      setFaultNote(`天气档位已切到「${id}」`)
      await saveValues({ weather_scenario: id })
    } catch (err) {
      setFaultNote(`切天气失败：${errText(err)}`)
    }
  }

  async function upload(file: File) {
    setUploadBusy(true)
    setSearchNote(null)
    try {
      const doc = await endpoints.uploadKnowledge(file)
      setDocs((list) => [doc, ...list])
      // 切片是后台线程，状态从 processing → ready，轮询几次把状态追上
      for (let i = 0; i < 8; i += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1200))
        const list = await endpoints.knowledgeDocs()
        setDocs(list)
        if (list.find((item) => item.id === doc.id)?.status !== 'processing') break
      }
    } catch (err) {
      setSearchNote(`上传失败：${errText(err)}`)
    } finally {
      setUploadBusy(false)
    }
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault()
    const file = event.dataTransfer.files[0]
    if (file) void upload(file)
  }

  async function search() {
    const text = question.trim()
    if (!text) {
      setHits(null)
      setSearchNote(null)
      return
    }
    setSearchNote(null)
    try {
      const result = await endpoints.searchKnowledge(text, 3)
      setHits(result.hits ?? [])
      if (!result.hits?.length) setSearchNote('未检索到相关内容。')
    } catch (err) {
      setHits([])
      setSearchNote(`检索失败：${errText(err)}`)
    }
  }

  const maskedKey = asStr(items.get('llm_api_key'))

  return (
    <PageFrame title="设置">
      <div className="flex flex-col items-start">
        {loadError ? (
          <p className="w-full bg-[#FFF4CC] px-5 py-3 text-sm leading-normal text-[#8A6414]">
            配置没读上来：{loadError}（下面显示的是默认值，改动会尝试写回后端）
          </p>
        ) : null}

        <section className="w-full px-5 py-5 text-left">
          <h2 className="text-paper">运行模式</h2>
          <p className="mt-1 text-sm leading-normal text-mute">
            切到真机后模拟器会停，读数改为等真设备心跳。切换会广播 mode_changed，顶栏徽章跟着变。
          </p>
          <div className="mt-4 flex justify-start gap-3" role="group" aria-label="运行模式">
            <ModeButton current={mode} value="mock" onPick={setMode} label="模拟" />
            <ModeButton current={mode} value="real" onPick={setMode} label="真机" />
          </div>
          <p className={`mt-3 text-sm leading-normal ${modeError ? 'text-danger' : 'text-mute'}`}>
            {modeError ?? (live ? 'WebSocket 已连接，模式变更会实时同步。' : 'WebSocket 未连接，模式以后端返回为准。')}
          </p>
        </section>

        <section className="w-full border-t border-[#EEF0F3] px-5 py-5 text-left">
          <h2 className="text-paper">模型服务</h2>
          <div className="mt-4 grid gap-3">
            <label className="grid gap-1 text-base text-dim">
              服务商
              <select
                value={provider}
                onChange={(event) => {
                  const next = event.target.value === 'deepseek' ? 'deepseek' : 'glm'
                  setProvider(next)
                  void saveValues({ llm_provider: next })
                }}
                className="h-11 rounded-btn border border-line bg-panel px-3 text-base text-paper"
              >
                <option value="glm">GLM-4-Flash</option>
                <option value="deepseek">DeepSeek</option>
              </select>
            </label>
            <label className="grid gap-1 text-base text-dim">
              密钥
              <input
                type="password"
                value={apiKey}
                // 后端只回掩码，占位符里显示掩码，留空表示不改
                placeholder={maskedKey || '未配置'}
                onChange={(event) => setApiKey(event.target.value)}
                className="h-11 rounded-btn border border-line px-3 text-base text-paper"
                autoComplete="off"
              />
            </label>
            <div className="flex flex-wrap items-center justify-start gap-3">
              <button
                type="button"
                disabled={!apiKey.trim() || saving}
                className="h-11 rounded-btn bg-tea px-4 text-base text-white hover:bg-teaHover active:bg-teaPress disabled:opacity-50"
                onClick={() => {
                  void saveValues({ llm_api_key: apiKey.trim() }).then(() => {
                    // 保存成功就把输入框清空，避免轮询期间把明文留在页面上
                    setApiKey('')
                  })
                }}
              >
                保存密钥
              </button>
              <button
                type="button"
                className="h-11 rounded-btn border border-line px-4 text-base text-paper hover:border-tea hover:text-tea"
                onClick={() => void probeModel()}
              >
                测试连接
              </button>
              {probe ? <p className="num text-sm text-paper">{probe}</p> : null}
            </div>
            {saveNote ? <p className="text-sm leading-normal text-mute">{saveNote}</p> : null}
          </div>
        </section>

        <section className="w-full border-t border-[#EEF0F3] px-5 py-5 text-left">
          <h2 className="text-paper">智能体</h2>
          <p className="mt-1 text-sm leading-normal text-mute">
            提示词与开关改完即生效（PUT /api/agents/{'{agent_key}'}）。工具权限由后端固定，这里只读。
            {agentsSample ? '当前展示的是本地样例（后端 agents 表为空），改动不会落库。' : ''}
          </p>
          <ul className="mt-4 grid gap-2">
            {agents.map((agent) => {
              const open = openKey === agent.agent_key
              return (
                <li key={agent.agent_key} className="rounded-xl border border-line">
                  <button
                    type="button"
                    className="flex w-full items-center justify-start gap-3 px-3 py-3 text-left"
                    onClick={() => setOpenKey(open ? null : agent.agent_key)}
                  >
                    <span className="text-lg" aria-hidden="true">
                      {agent.avatar ?? '🤖'}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm text-paper">{agent.name}</span>
                      <span className="block truncate text-xs text-mute">
                        {agent.tools_json?.length ? agent.tools_json.join('、') : '（无工具）'}
                      </span>
                    </span>
                    <span className={`text-xs ${agent.enabled ? 'text-tea' : 'text-mute'}`}>
                      {agent.enabled ? '启用' : '停用'}
                    </span>
                  </button>
                  {open ? (
                    <div className="grid gap-3 border-t border-line px-3 py-3">
                      <div className="overflow-hidden rounded-xl border border-line bg-panel">
                        <table className="w-full border-collapse text-left text-sm leading-normal">
                          <tbody>
                            <tr>
                              <th className="w-24 border-b border-line bg-[#F7F8FA] px-4 py-3 text-left text-sm font-normal text-dim">
                                身份
                              </th>
                              <td className="border-b border-line px-4 py-3 text-paper">
                                {agent.name}（{agent.agent_key}）
                              </td>
                            </tr>
                            <tr>
                              <th className="w-24 border-b border-line bg-[#F7F8FA] px-4 py-3 text-left text-sm font-normal text-dim">
                                模型
                              </th>
                              <td className="num border-b border-line px-4 py-3 text-paper">
                                {agent.model ?? provider} · T={agent.temperature ?? 0.3}
                              </td>
                            </tr>
                            <tr>
                              <th className="w-24 bg-[#F7F8FA] px-4 py-3 text-left align-top text-sm font-normal text-dim">
                                提示词
                              </th>
                              <td className="px-4 py-3">
                                <textarea
                                  value={promptDraft[agent.agent_key] ?? ''}
                                  onChange={(event) =>
                                    setPromptDraft((current) => ({ ...current, [agent.agent_key]: event.target.value }))
                                  }
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
                            </tr>
                          </thead>
                          <tbody>
                            {(agent.tools_json ?? []).map((name) => (
                              <tr key={name} className="border-t border-line">
                                <td className="num px-3 py-1.5 align-middle text-paper">{name}</td>
                                <td className="num px-3 py-1.5 align-middle text-paper">{agent.temperature ?? 0.3}</td>
                              </tr>
                            ))}
                            {agent.tools_json?.length ? null : (
                              <tr className="border-t border-line">
                                <td className="px-3 py-1.5 text-mute" colSpan={2}>
                                  这个智能体没有挂工具
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                      <div className="flex flex-wrap items-center gap-4">
                        <label className="flex items-center gap-2 text-sm text-paper">
                          <input
                            type="checkbox"
                            className="accent-tea"
                            checked={agent.enabled}
                            onChange={(event) => void toggleAgent(agent, event.target.checked)}
                          />
                          启用这个智能体
                        </label>
                        <button
                          type="button"
                          className="h-11 rounded-btn bg-tea px-4 text-base text-white hover:bg-teaHover active:bg-teaPress"
                          onClick={() => void savePrompt(agent)}
                        >
                          保存提示词
                        </button>
                      </div>
                    </div>
                  ) : null}
                </li>
              )
            })}
            {agents.length === 0 ? <li className="text-sm text-mute">后端没有智能体记录（或接口没通）。</li> : null}
          </ul>
        </section>

        <section className="w-full border-t border-[#EEF0F3] px-5 py-5 text-left">
          <h2 className="text-paper">设备调试</h2>
          <p className="mt-1 text-sm leading-normal text-mute">
            缺省列出全部设备（含 Mock 与真机），按 is_mock 标注来源。指令走 POST /api/devices/{'{id}'}/cmd。
          </p>
          <div className="mt-4 grid gap-3">
            <label className="grid gap-1 text-base text-dim">
              设备
              <select
                value={deviceId}
                onChange={(event) => setDeviceId(event.target.value)}
                className="h-11 rounded-btn border border-line bg-panel px-3 text-base text-paper"
              >
                {devices.map((device) => (
                  <option key={device.device_id} value={device.device_id}>
                    {device.name} · {device.device_id}
                    {device.is_mock ? ' · Mock' : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-base text-dim">
              动作
              <select
                value={action}
                onChange={(event) => setAction(event.target.value)}
                className="h-11 rounded-btn border border-line bg-panel px-3 text-base text-paper"
              >
                {DEVICE_ACTIONS.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            {action === 'pump' ? (
              <label className="grid gap-1 text-base text-dim">
                时长（秒）
                <input
                  value={duration}
                  onChange={(event) => setDuration(event.target.value.replace(/[^\d]/g, ''))}
                  className="num h-11 rounded-btn border border-line px-3 text-base text-paper"
                />
              </label>
            ) : null}
            <button
              type="button"
              disabled={!deviceId || cmdBusy}
              className="h-11 w-fit rounded-btn bg-tea px-4 text-base text-white hover:bg-teaHover active:bg-teaPress disabled:opacity-50"
              onClick={() => void sendCmd()}
            >
              {cmdBusy ? '下发中…' : '发送'}
            </button>
            {ack ? (
              <pre className="num overflow-auto rounded-xl bg-[#F7F8FA] p-3 text-xs leading-normal text-dim">{ack}</pre>
            ) : null}
          </div>
        </section>

        <section className="w-full border-t border-[#EEF0F3] px-5 py-5 text-left">
          <h2 className="text-paper">故障注入</h2>
          <p className="mt-1 text-sm leading-normal text-mute">
            写进后端模拟器（不是前端的假开关），注入后大屏与任务流会真的受影响。离线类故障保留 120 秒。
          </p>
          <div className="mt-4 flex flex-wrap justify-start gap-3">
            {faults.map((fault) => {
              const on = faultActive(mock, fault.id)
              return (
                <button
                  key={fault.id}
                  type="button"
                  aria-pressed={on}
                  title={fault.hint}
                  onClick={() => void toggleFault(fault.id)}
                  className={`h-11 rounded-btn border px-4 text-base ${
                    on ? 'border-tea bg-tea text-white' : 'border-line text-paper hover:border-tea hover:text-tea'
                  }`}
                >
                  {fault.label}
                  {on ? ' · 已注入' : ''}
                </button>
              )
            })}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <span className="text-base text-dim">Mock 天气</span>
            {weathers.map((item) => (
              <button
                key={item.id}
                type="button"
                aria-pressed={mock?.weather === item.id}
                onClick={() => void switchWeather(item.id)}
                className={`h-11 rounded-btn border px-4 text-base ${
                  mock?.weather === item.id
                    ? 'border-tea bg-tea text-white'
                    : 'border-line text-paper hover:border-tea hover:text-tea'
                }`}
              >
                {item.label}
              </button>
            ))}
            <span className="num text-sm text-mute">
              模拟器 {mock?.running ? '运行中' : '未启动'} · 土壤 {mock?.soil_moisture ?? '—'}%
            </span>
          </div>
          {faultNote ? <p className="mt-3 text-sm leading-normal text-mute">{faultNote}</p> : null}
        </section>

        <section className="w-full border-t border-[#EEF0F3] px-5 py-5 text-left">
          <h2 className="text-paper">调度参数</h2>
          <p className="mt-1 text-sm leading-normal text-mute">改一项写一项，全部落 settings 表，后端下一轮读取即生效。</p>
          <div className="mt-4 grid gap-4">
            <label className="flex items-center gap-2 text-base text-paper">
              <input
                type="checkbox"
                className="accent-tea"
                checked={parallel}
                onChange={(event) => {
                  setParallel(event.target.checked)
                  void saveValues({ parallel_enabled: event.target.checked })
                }}
              />
              并行会诊
            </label>
            <label className="grid gap-1 text-base text-dim">
              最多重试
              <input
                type="number"
                min={0}
                max={3}
                value={retries}
                onChange={(event) => setRetries(Number(event.target.value))}
                onBlur={() => void saveValues({ max_retries: retries })}
                className="num h-11 rounded-btn border border-line px-3 text-base text-paper"
              />
            </label>
            <div className="grid gap-1 text-base text-dim">
              目标湿度区间（%）
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  value={range[0]}
                  onChange={(event) => setRange([Number(event.target.value), range[1]])}
                  onBlur={() => void saveValues({ irrigation_default_range: range })}
                  className="num h-11 w-24 rounded-btn border border-line px-3 text-base text-paper"
                />
                <span className="text-mute">–</span>
                <input
                  type="number"
                  value={range[1]}
                  onChange={(event) => setRange([range[0], Number(event.target.value)])}
                  onBlur={() => void saveValues({ irrigation_default_range: range })}
                  className="num h-11 w-24 rounded-btn border border-line px-3 text-base text-paper"
                />
              </div>
            </div>
            <label className="grid gap-1 text-base text-dim">
              巡园定时（cron）
              <input
                value={cron}
                onChange={(event) => setCron(event.target.value)}
                onBlur={() => void saveValues({ schedule_cron: cron })}
                className="num h-11 rounded-btn border border-line px-3 text-base text-paper"
              />
            </label>
            <p className="num text-sm text-mute">mode={mode} · 保存状态：{saving ? '写入中…' : (saveNote ?? '已同步')}</p>
          </div>
        </section>

        <section className="w-full border-t border-[#EEF0F3] px-5 py-5 text-left">
          <h2 className="text-paper">知识库</h2>
          <p className="mt-1 text-sm leading-normal text-mute">
            上传后后台线程切片入库，状态从 processing 变 ready。检索走 /api/knowledge/search，空数组表示没命中。
          </p>
          <label
            className="mt-4 grid h-28 cursor-pointer place-items-center rounded-xl border border-dashed border-line bg-[#F7F8FA] text-sm text-mute"
            onDragOver={(event) => event.preventDefault()}
            onDrop={onDrop}
          >
            {uploadBusy ? '上传并切片中…' : '把 .pdf / .txt / .md 拖到这里，或点此选择'}
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.txt,.md"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) void upload(file)
                event.target.value = ''
              }}
            />
          </label>
          <ul className="mt-3 grid gap-2">
            {docs.map((doc) => (
              <li key={doc.id} className="flex items-center justify-between gap-3 text-sm">
                <span className="min-w-0 truncate text-paper">{doc.title}</span>
                <span className="flex shrink-0 items-center gap-3">
                  <span className="num text-xs text-mute">{doc.chunk_count ?? 0} 片</span>
                  <span
                    className={
                      doc.status === 'ready' ? 'text-tea' : doc.status === 'failed' ? 'text-danger' : 'text-mute'
                    }
                  >
                    {doc.status === 'ready' ? '已就绪' : doc.status === 'failed' ? '入库失败' : '处理中'}
                  </span>
                  <button
                    type="button"
                    className="text-xs text-mute hover:text-danger"
                    onClick={() => {
                      void endpoints
                        .deleteKnowledge(doc.id)
                        .then(() => setDocs((list) => list.filter((item) => item.id !== doc.id)))
                        .catch((err: unknown) => setSearchNote(`删除失败：${errText(err)}`))
                    }}
                  >
                    删除
                  </button>
                </span>
              </li>
            ))}
            {docs.length === 0 ? <li className="text-sm text-mute">还没有文档。</li> : null}
          </ul>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void search()
              }}
              placeholder="输入问题，例如 缺水"
              className="h-11 min-w-0 flex-1 rounded-btn border border-line px-3 text-base text-paper"
            />
            <button
              type="button"
              className="h-11 rounded-btn bg-tea px-4 text-base text-white hover:bg-teaHover active:bg-teaPress"
              onClick={() => void search()}
            >
              检索
            </button>
          </div>
          {searchNote ? <p className="mt-3 text-sm leading-normal text-mute">{searchNote}</p> : null}
          <ul className="mt-3 grid gap-2">
            {(hits ?? []).map((hit) => (
              <li key={`${hit.doc_id}-${hit.chunk_index}`} className="rounded-xl bg-[#F7F8FA] px-3 py-3">
                <p className="text-sm text-paper">
                  {hit.title} <span className="num text-mute">{hit.score.toFixed(2)}</span>
                </p>
                <p className="mt-1 text-sm leading-normal text-dim">{hit.chunk_text}</p>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </PageFrame>
  )
}

/** 模拟器状态 → 某个故障是否正在生效 */
function faultActive(mock: MockStateDto | null, id: string) {
  const faults = mock?.faults
  if (!faults) return false
  if (id === 'offline') return Object.values(faults.offline ?? {}).some((left) => left > 0)
  if (id === 'ack_timeout') return (faults.ack_timeout_until ?? 0) * 1000 > Date.now()
  if (id === 'dry_soil') return Boolean(faults.dry_soil)
  if (id === 'stuck_moisture') return Boolean(faults.stuck_moisture)
  if (id === 'sensor_jitter') return Boolean(faults.sensor_jitter)
  return false
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
      className={`h-11 rounded-btn border px-6 text-base ${
        active ? 'border-tea bg-tea text-white' : 'border-line text-paper hover:border-tea hover:text-tea'
      }`}
    >
      {label}
    </button>
  )
}
