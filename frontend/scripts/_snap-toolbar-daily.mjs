import { writeFileSync, rmSync } from 'node:fs'
import { spawn } from 'node:child_process'

const PORT = 9412
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/ct2_profile'
rmSync(profile, { recursive: true, force: true })
const chrome = spawn('C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe',
  ['--headless=new', '--disable-gpu', '--hide-scrollbars', `--remote-debugging-port=${PORT}`,
   `--user-data-dir=${profile}`, '--no-first-run', '--hide-crash-restore-bubble', '--window-size=1440,1000', 'about:blank'],
  { stdio: 'ignore' })
await new Promise((r) => setTimeout(r, 2500))
const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()
const page = list.find((i) => i.type === 'page')
const ws = new WebSocket(page.webSocketDebuggerUrl)
let id = 0
const pend = new Map()
const send = (m, p) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: p })) })
ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id) } }
await new Promise((r) => ws.onopen = r)
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const shot = (name, clip) => send('Page.captureScreenshot', { format: 'png', clip, scale: 1 })

await send('Page.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })

await send('Page.navigate', { url: 'http://localhost:5173/canvas' })
await wait(9000)
const cap = await send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 800, width: 1440, height: 200, scale: 1 } })
writeFileSync('D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/canvas-toolbar/toolbar-zoom.png', Buffer.from(cap.data, 'base64'))

await send('Page.navigate', { url: 'http://localhost:5173/report' })
await wait(9000)
await send('Runtime.evaluate', { expression: `(() => { const b = [...document.querySelectorAll('button')].find((e) => e.textContent.includes('生成日报')); if (b) b.click(); return true })()` })
await wait(2500)
await send('Runtime.evaluate', { expression: `(() => { const b = [...document.querySelectorAll('button')].find((e) => e.textContent.includes('生成日报')); if (b) b.click(); return true })()` })
await wait(2500)
await send('Runtime.evaluate', { expression: `(() => { const els = [...document.querySelectorAll('h2,h3,button,p')]; const b = els.find((e) => e.textContent.trim().startsWith('日报')); if (b) { b.scrollIntoView({ block: 'start' }); window.scrollBy(0, -70) } return true })()` })
await wait(1200)
const y = (await send('Runtime.evaluate', { expression: 'window.scrollY', returnByValue: true })).result?.value ?? 0
const cap2 = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: y, width: 1440, height: 1150, scale: 1 } })
writeFileSync('D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/canvas-toolbar/daily-section.png', Buffer.from(cap2.data, 'base64'))
chrome.kill()
process.exit(0)
