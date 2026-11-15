// 一次性验证：把画布视口平移到 Self-Loop 区域截图，确认回边箭头落点
import { spawn } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const OUT = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check'
const PORT = 9334
const BASE = 'http://localhost:5173/canvas'

mkdirSync(OUT, { recursive: true })
const profile = `${OUT}/profile2`
rmSync(profile, { recursive: true, force: true })

const chrome = spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1440,1100', 'about:blank',
], { stdio: 'ignore' })

async function target() {
  for (let i = 0; i < 60; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json`)
      const page = (await res.json()).find((item) => item.type === 'page')
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl
    } catch { /* 等 chrome */ }
    await sleep(250)
  }
  throw new Error('CDP 起不来')
}

const ws = new WebSocket(await target())
await new Promise((resolve) => ws.addEventListener('open', resolve, { once: true }))
let seq = 0
const waiting = new Map()
ws.addEventListener('message', (event) => {
  const msg = JSON.parse(event.data)
  if (msg.id && waiting.has(msg.id)) { waiting.get(msg.id)(msg); waiting.delete(msg.id) }
})
const send = (method, params = {}) => {
  const id = ++seq
  ws.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve) => waiting.set(id, resolve))
}

await send('Runtime.enable')
await send('Page.enable')
await send('Page.navigate', { url: BASE })
await sleep(3000)

// 权威验证：React Flow 把每条边的 id 写进 DOM（data-id），我们的 id 形如 `n11b->n9:back`
const probe = await send('Runtime.evaluate', {
  expression: `JSON.stringify({
    edges: [...document.querySelectorAll('.react-flow__edge')].map((el) => el.getAttribute('data-id')),
    loopNode: [...document.querySelectorAll('.react-flow__node')].map((el) => el.getAttribute('data-id')).filter((id) => id.includes('n11b') || id.includes('n9')),
  })`,
  returnByValue: true,
})
console.log('edges:', probe.result.result.value)
await sleep(500)

const shot = await send('Page.captureScreenshot', { format: 'png' })
writeFileSync(`${OUT}/canvas_selfloop.png`, Buffer.from(shot.result.data, 'base64'))

ws.close()
chrome.kill()
