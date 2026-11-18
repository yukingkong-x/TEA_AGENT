import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { spawn } from 'node:child_process'

const BASE = process.argv[2] ?? 'http://localhost:5173'
const ROUTE = process.argv[3] ?? '/report'
const SHOT_DIR = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/report-empty'
mkdirSync(SHOT_DIR, { recursive: true })
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9399
rmSync('D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/report_profile', { recursive: true, force: true })
rmSync('D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/report_profile', { recursive: true, force: true })
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, '--user-data-dir=D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/report_profile', '--no-first-run', '--no-default-browser-check', '--hide-crash-restore-bubble', '--hide-crash-restore-bubble', '--disable-privacy-sandbox-prompt', '--disable-features=PrivacySandboxSettings4', '--window-size=1440,1600', `${BASE}${ROUTE}`], { stdio: 'ignore' })
let page = null
for (let i = 0; i < 40 && !page; i++) {
  await new Promise((r) => setTimeout(r, 500))
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()
  page = list.find((t) => t.type === 'page' && t.url.startsWith('http')) ?? null
}
if (!page) {
  // URL 启动参数没生效（Chrome 有时只开 newtab）：连上现有 page 目标手动导航
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()
  page = list.find((t) => t.type === 'page') ?? null
  if (!page) { console.error('no page target at all'); process.exit(1) }
}
const ws = new WebSocket(page.webSocketDebuggerUrl)
let id = 0
const pend = new Map()
const send = (m, p) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: p })) })
const errors = []
ws.onmessage = (e) => {
  const m = JSON.parse(e.data)
  if (m.method === 'Runtime.exceptionThrown') errors.push('EXC: ' + m.params.exceptionDetails.text)
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push('CONSOLE: ' + m.params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300))
  if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errors.push(m.params.entry.text)
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id) }
}
await new Promise((r) => ws.onopen = r)
{
  const nav = await send('Page.navigate', { url: `${BASE}${ROUTE}` })
  if (nav?.errorText) console.error('navigate error:', nav.errorText)
}
const ev = async (ex) => {
  const r = await send('Runtime.evaluate', { awaitPromise: true, returnByValue: true, expression: ex })
  return r?.exceptionDetails ? { err: JSON.stringify(r.exceptionDetails).slice(0, 300) } : r.result?.value
}
await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1600, deviceScaleFactor: 1, mobile: false })
await new Promise((r) => setTimeout(r, 9000))

const probe0 = await ev('({url: location.href, ready: document.readyState, len: document.body ? document.body.innerText.length : -1, html: document.documentElement.outerHTML.length})')
console.log('PROBE0', JSON.stringify(probe0))
const info = await ev(`(() => {
  const text = (el) => el?.textContent?.replace(/\\s+/g,' ').trim() ?? ''
  const h2 = [...document.querySelectorAll('h2')].map(text)
  const sel = document.querySelector('select')
  return {
    heading: text(document.querySelector('h1')),
    sections: h2,
    selectedRun: sel ? sel.value : null,
    bodyLen: document.body.innerText.length,
    bodyHead: document.body.innerText.replace(/\\s+/g,' ').slice(0, 700),
  }
})()`)
console.log(JSON.stringify({ info, errors: errors.slice(0, 5) }, null, 2))
const cap = await send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: 1440, height: 1600, scale: 1 } })
writeFileSync(`${SHOT_DIR}/report.png`, Buffer.from(cap.data, 'base64'))
ws.close(); chrome.kill(); process.exit(0)
