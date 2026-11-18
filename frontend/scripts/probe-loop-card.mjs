/**
 * 总控页闭环卡 + 墒情胶囊验收：
 * 1. 「土壤湿度」重复卡已消失，「最近一次闭环」卡在位
 * 2. 五步（巡园/会诊/决策/执行/验证）都有真实文案，徽章与 run.status 一致
 * 3. 顶部墒情胶囊：读数 0 时显示「探头未插入」，不再出现 -999 / 38.5 假数
 * 4. 0 console error
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { spawn } from 'node:child_process'

const BASE = process.argv[2] ?? 'http://localhost:5173'
const SHOT_DIR = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check'
mkdirSync(SHOT_DIR, { recursive: true })
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9387
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/loop_profile'

const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--window-size=1440,1800', 'about:blank'], { stdio: 'ignore' })

await new Promise((r) => setTimeout(r, 2500))
const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()
const page = list.find((i) => i.type === 'page')
const ws = new WebSocket(page.webSocketDebuggerUrl)
let id = 0
const pend = new Map()
const send = (m, p) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: p })) })
const errors = []
ws.onmessage = (e) => {
  const m = JSON.parse(e.data)
  if (m.method === 'Runtime.exceptionThrown') errors.push(m.params.exceptionDetails.text)
  if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errors.push(m.params.entry.text)
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id) }
}
await new Promise((r) => ws.onopen = r)
const ev = async (ex) => (await send('Runtime.evaluate', { awaitPromise: true, returnByValue: true, expression: ex })).result?.value

await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1800, deviceScaleFactor: 1, mobile: false })
await send('Page.navigate', { url: BASE })
await new Promise((r) => setTimeout(r, 11000))

const out = await ev(`(() => {
  const text = (el) => el?.textContent?.replace(/\\s+/g,' ').trim() ?? ''
  const h2 = [...document.querySelectorAll('h2')].find((h) => text(h) === '最近一次闭环')
  const loop = h2 ? h2.closest('div[class*="rounded-card"], section') ?? h2.parentElement?.parentElement?.parentElement : null
  const soilCard = [...document.querySelectorAll('h2')].find((h) => text(h) === '土壤湿度')
  const chip = [...document.querySelectorAll('p')].find((p) => /土壤(湿度|探头)/.test(text(p)))
  const steps = loop ? [...loop.querySelectorAll('li')].map((li) => text(li)) : []
  const badge = loop ? [...loop.querySelectorAll('span')].map(text).find((t) => ['闭环','转人工','未达标','进行中'].includes(t)) : null
  const pageText = document.body.innerText
  return {
    loopTitle: loop ? text(loop.querySelector('h2')) : null,
    badge,
    steps,
    soilCardExists: Boolean(soilCard),
    chip: text(chip),
    hasSentinel: /-999|38\\.5%/.test(pageText),
    hasMockBadge: pageText.includes('模拟'),
    gaugeCardInPanel: Boolean(document.querySelector('section[aria-label="实时传感器读数"]')),
  }
})()`)

console.log(JSON.stringify(out, null, 2))
console.log('console errors:', errors.length, errors.slice(0, 3))

const cap = await send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: 1440, height: 1800, scale: 1 } })
writeFileSync(`${SHOT_DIR}/loop-card.png`, Buffer.from(cap.data, 'base64'))
ws.close(); chrome.kill(); process.exit(0)
