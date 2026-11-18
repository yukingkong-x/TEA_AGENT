import { writeFileSync, rmSync } from 'node:fs'
import { spawn } from 'node:child_process'

const PORT = 9415
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/av_profile'
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
const errors = []
ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') errors.push(m.params.entry.text); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id) } }
await new Promise((r) => ws.onopen = r)
await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable')
const ev = async (ex) => (await send('Runtime.evaluate', { awaitPromise: true, returnByValue: true, expression: ex })).result?.value
await send('Page.navigate', { url: 'http://localhost:5173/settings' })
await new Promise((r) => setTimeout(r, 8000))
const info = await ev(`(() => {
  const imgs = [...document.querySelectorAll('img[src^="/avatars/"]')]
  return { count: imgs.length, loaded: imgs.filter((i) => i.complete && i.naturalWidth > 0).length }
})()`)
console.log('AVATARS', JSON.stringify(info))
const cap = await send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 300, width: 1100, height: 700, scale: 1 } })
writeFileSync('D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/canvas-toolbar/settings-avatars.png', Buffer.from(cap.data, 'base64'))
console.log('ERRORS', errors.length)
process.exit(0)
