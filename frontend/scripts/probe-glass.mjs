/**
 * 磨砂玻璃卡片验收（CDP）。
 *
 * 判定：
 * 1. 每页都有 .glass-card（不再是一整张白板）
 * 2. 鼠标移入卡片：加 is-live、::before 光斑 opacity→1、::after 边框高光 opacity→1
 * 3. 倾斜角度 ≤ 4°（读 inline style 的 rotateX/rotateY）
 * 4. 移出后 transform 清空（平滑复原由 CSS transition 负责）
 * 5. 全程 0 console error
 *
 * 用法：node frontend/scripts/probe-glass.mjs [baseUrl]
 */
import { spawn } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'

const BASE = (process.argv[2] || 'http://localhost:5173').replace(/\/+$/, '')
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9373
const DIR = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check'
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/glass_profile'
rmSync(profile, { recursive: true, force: true })
mkdirSync(profile, { recursive: true })
mkdirSync(DIR, { recursive: true })

const chrome = spawn(
  CHROME,
  ['--headless=new', '--disable-gpu', '--hide-scrollbars', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--window-size=1440,1000', 'about:blank'],
  { stdio: 'ignore' },
)
await new Promise((r) => setTimeout(r, 2500))
const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()
const page = list.find((i) => i.type === 'page')
const ws = new WebSocket(page.webSocketDebuggerUrl)
let id = 0
const pend = new Map()
const send = (method, params) =>
  new Promise((res) => {
    const i = ++id
    pend.set(i, res)
    ws.send(JSON.stringify({ id: i, method, params }))
  })
ws.onmessage = (e) => {
  const m = JSON.parse(e.data)
  if (m.id && pend.has(m.id)) {
    pend.get(m.id)(m.result)
    pend.delete(m.id)
  }
}
await new Promise((r) => (ws.onopen = r))
await send('Runtime.enable')
await send('Page.enable')

const errors = []
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data)
  if (m.method === 'Runtime.exceptionThrown')
    errors.push('EXC: ' + String(m.params.exceptionDetails.exception?.description || '').slice(0, 200))
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error')
    errors.push('ERR: ' + m.params.args.map((a) => a.value ?? '').join(' ').slice(0, 200))
})

const ev = async (expression) =>
  (await send('Runtime.evaluate', { awaitPromise: true, returnByValue: true, expression })).result?.value
const shot = async (name) => {
  const res = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(`${DIR}/${name}.png`, Buffer.from(res.data, 'base64'))
}
const move = (x, y) => send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'none' })

await send('Page.navigate', { url: BASE + '/' })
await new Promise((r) => setTimeout(r, 5000))

const box = await ev(`(() => {
  const el = document.querySelector('section[aria-label="实时传感器读数"]')
  if (!el) return null
  const r = el.getBoundingClientRect()
  return { x: r.x, y: r.y, w: r.width, h: r.height }
})()`)

let hover = null
let rest = null
if (box) {
  await shot('glass-dashboard-rest')
  // 落在卡片右下角：能同时看出光斑位置和倾斜方向
  await move(Math.round(box.x + box.w * 0.72), Math.round(box.y + box.h * 0.68))
  await new Promise((r) => setTimeout(r, 220))
  hover = await ev(`(() => {
    const el = document.querySelector('section[aria-label="实时传感器读数"]')
    const cs = getComputedStyle(el)
    return {
      live: el.classList.contains('is-live'),
      inline: el.style.transform,
      mx: el.style.getPropertyValue('--mx'),
      my: el.style.getPropertyValue('--my'),
      spot: getComputedStyle(el, '::before').opacity,
      rim: getComputedStyle(el, '::after').opacity,
      backdrop: cs.backdropFilter,
      bg: cs.backgroundImage.slice(0, 40),
    }
  })()`)
  await shot('glass-dashboard-hover')

  await move(4, 4)
  await new Promise((r) => setTimeout(r, 700))
  rest = await ev(`(() => {
    const el = document.querySelector('section[aria-label="实时传感器读数"]')
    return { live: el.classList.contains('is-live'), inline: el.style.transform }
  })()`)
}

const angle = (inline) => {
  const rx = /rotateX\(([-\d.]+)deg\)/.exec(inline || '')
  const ry = /rotateY\(([-\d.]+)deg\)/.exec(inline || '')
  return { rx: rx ? Number(rx[1]) : 0, ry: ry ? Number(ry[1]) : 0 }
}

const pages = [
  ['/report', 'glass-report'],
  ['/settings', 'glass-settings'],
  ['/tasks', 'glass-tasks'],
  ['/chat', 'glass-chat'],
]
const counts = {}
for (const [path, name] of pages) {
  await send('Page.navigate', { url: BASE + path })
  await new Promise((r) => setTimeout(r, 3200))
  counts[path] = await ev(`document.querySelectorAll('.glass-card').length`)
  await shot(name)
}

console.log(
  JSON.stringify(
    {
      hover: hover && { live: hover.live, angle: angle(hover.inline), spot: hover.spot, rim: hover.rim, mx: hover.mx, my: hover.my, backdrop: hover.backdrop },
      rest,
      cardsPerPage: counts,
      errors,
    },
    null,
    2,
  ),
)
ws.close()
chrome.kill()
