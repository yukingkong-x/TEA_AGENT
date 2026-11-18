/**
 * 侧边栏玻璃胶囊验收（CDP）。
 *
 * 判定：
 * 1. 文字标签回来了（每个导航项都有可见文字）
 * 2. 静止时胶囊与当前项的 rect 完全重合（±1px）
 * 3. 切换时胶囊有位移中间态（transform 不是终点），且移动中 scaleY > 1（沿运动方向拉长）
 * 4. 到位后 scaleY 回到 1
 * 5. 无 console error
 * 6. 出图：静止 / 移动中 / 到位
 *
 * 用法：node frontend/scripts/probe-sidebar-pill.mjs [baseUrl]
 */
import { spawn } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'

const BASE = (process.argv[2] || 'http://localhost:5173').replace(/\/+$/, '')
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9367
const DIR = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check'
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/pill_profile'
rmSync(profile, { recursive: true, force: true })
mkdirSync(profile, { recursive: true })
mkdirSync(DIR, { recursive: true })

const chrome = spawn(
  CHROME,
  [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    '--window-size=1440,1000',
    'about:blank',
  ],
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
    errors.push('EXC: ' + String(m.params.exceptionDetails.exception?.description || '').slice(0, 240))
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error')
    errors.push('ERR: ' + m.params.args.map((a) => a.value ?? '').join(' ').slice(0, 240))
})

const ev = async (expression) =>
  (await send('Runtime.evaluate', { awaitPromise: true, returnByValue: true, expression })).result?.value

const shot = async (name) => {
  const res = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(`${DIR}/${name}.png`, Buffer.from(res.data, 'base64'))
}

const measure = () =>
  ev(`(() => {
    const pill = document.querySelector('.nav-pill')
    const active = [...document.querySelectorAll('nav[aria-label="页面"] a')].find((a) => a.getAttribute('aria-current') === 'page')
    const pr = pill.getBoundingClientRect()
    const ar = active ? active.getBoundingClientRect() : null
    const cs = getComputedStyle(pill)
    const m = new DOMMatrixReadOnly(cs.transform === 'none' ? '' : cs.transform)
    return {
      pill: { x: Math.round(pr.x), y: Math.round(pr.y), w: Math.round(pr.width), h: Math.round(pr.height) },
      active: ar ? { x: Math.round(ar.x), y: Math.round(ar.y), w: Math.round(ar.width), h: Math.round(ar.height), text: active.innerText.trim() } : null,
      scale: { x: Number(m.a.toFixed(3)), y: Number(m.d.toFixed(3)) },
      labels: [...document.querySelectorAll('nav[aria-label="页面"] a')].map((a) => a.innerText.trim()),
      pillBg: cs.backgroundColor,
      pillShadow: cs.boxShadow.slice(0, 90),
    }
  })()`)

await send('Page.navigate', { url: BASE + '/' })
await new Promise((r) => setTimeout(r, 4000))

const rest = await measure()
await shot('sidebar-pill-rest')

// 点「设置」：跨两个分组的长距离移动，最容易看出拉伸和回弹
await ev(`document.querySelector('nav[aria-label="页面"] a[href="/settings"]')?.click()`)
await new Promise((r) => setTimeout(r, 70))
const mid = await measure()
await shot('sidebar-pill-moving')
await new Promise((r) => setTimeout(r, 700))
const settled = await measure()
await shot('sidebar-pill-settled')

const close = (a, b) => a && b && Math.abs(a.x - b.x) <= 1 && Math.abs(a.y - b.y) <= 1 && Math.abs(a.w - b.w) <= 1 && Math.abs(a.h - b.h) <= 1

console.log(
  JSON.stringify(
    {
      rest: { aligned: close(rest.pill, rest.active), scale: rest.scale, active: rest.active?.text, labels: rest.labels },
      mid: { pill: mid.pill, active: mid.active, scale: mid.scale },
      settled: { aligned: close(settled.pill, settled.active), scale: settled.scale, active: settled.active?.text },
      style: { bg: rest.pillBg, shadow: rest.pillShadow },
      errors,
    },
    null,
    2,
  ),
)

ws.close()
chrome.kill()
