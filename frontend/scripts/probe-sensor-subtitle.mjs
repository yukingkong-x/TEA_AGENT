/** 验收：总控页实时传感标题下的说明小字（K10+MAX3485 · 10秒/次…）已删除 */
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { spawn } from 'node:child_process'

const BASE = process.argv[2] ?? 'http://localhost:5173'
const SHOT_DIR = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/sensor-subtitle'
mkdirSync(SHOT_DIR, { recursive: true })
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9405
rmSync('D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/ss_profile', { recursive: true, force: true })
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, '--user-data-dir=D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/ss_profile',
  '--no-first-run', '--no-default-browser-check', '--hide-crash-restore-bubble', '--disable-privacy-sandbox-prompt', '--window-size=1440,1000', `${BASE}/`], { stdio: 'ignore' })

let page = null
for (let i = 0; i < 40 && !page; i++) {
  await new Promise((r) => setTimeout(r, 500))
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()
  page = list.find((t) => t.type === 'page' && t.url.startsWith('http')) ?? null
}
if (!page) { console.error('no page target'); process.exit(1) }
const ws = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((r) => ws.onopen = r)
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
await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable')
await new Promise((r) => setTimeout(r, 9000))
const out = await (async () => {
  const r = await send('Runtime.evaluate', { returnByValue: true, expression: `(() => {
    const text = document.body.innerText.replace(/\\s+/g, ' ')
    const h2 = [...document.querySelectorAll('h2')].find((h) => h.textContent.trim() === '实时传感')
    return {
      hasSubtitle: /10 秒\\/次|MAX3485|拖动卡片换位/.test(text),
      h2Found: Boolean(h2),
      headerText: h2 ? h2.parentElement.innerText.replace(/\\s+/g, ' ') : null,
    }
  })()` })
  return r.result?.value
})()
console.log(JSON.stringify({ out, errors: errors.slice(0, 3) }, null, 2))
const cap = await send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: 1440, height: 1000, scale: 1 } })
writeFileSync(`${SHOT_DIR}/sensor.png`, Buffer.from(cap.data, 'base64'))
ws.close(); chrome.kill(); process.exit(0)
