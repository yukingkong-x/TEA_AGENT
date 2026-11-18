/**
 * 侧边栏图标轨验收（CDP）。
 *
 * 判定：
 * 1. 轨道是纯图标：宽度 ~72px，没有可见文字标签
 * 2. 悬停图标 → 右侧弹出文字提示（tooltip 可见且文本正确）
 * 3. 图标之间有分隔线（>=2 条）
 * 4. 点击图标能正常路由（点「报告」后 URL 变化）
 * 5. 全程无 console error
 *
 * 用法：node frontend/scripts/probe-sidebar.mjs [baseUrl]
 */
import { spawn } from 'node:child_process'
import { mkdirSync, rmSync } from 'node:fs'

const BASE = (process.argv[2] || 'http://localhost:5173').replace(/\/+$/, '')
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9352
const SHOT = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check/sidebar_rail.png'
const SHOT_HOVER = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check/sidebar_hover.png'
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/sidebar_profile'
rmSync(profile, { recursive: true, force: true })
mkdirSync(profile, { recursive: true })

const chrome = spawn(
  CHROME,
  ['--headless=new', '--disable-gpu', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--window-size=1440,1000', 'about:blank'],
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
  if (m.method === 'Runtime.exceptionThrown') errors.push('EXC: ' + String(m.params.exceptionDetails.exception?.description || '').slice(0, 300))
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors.push('ERR: ' + m.params.args.map((a) => a.value ?? '').join(' ').slice(0, 300))
})

const ev = async (expression) => (await send('Runtime.evaluate', { awaitPromise: true, returnByValue: true, expression })).result?.value
const shot = async (path) => {
  const { data } = await send('Page.captureScreenshot', { format: 'png' })
  const { writeFileSync } = await import('node:fs')
  writeFileSync(path, Buffer.from(data, 'base64'))
}
const hoverAt = async (x, y) => {
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'none' })
}

await send('Page.navigate', { url: BASE + '/' })
await new Promise((r) => setTimeout(r, 4000))

// 1. 纯图标轨：宽度 + 有无可见文字
const rail = await ev(`(() => {
  const aside = document.querySelector('aside')
  if (!aside) return null
  const w = aside.getBoundingClientRect().width
  // 可见文字 = 直接属于导航项且非 tooltip 的 span
  const labels = [...aside.querySelectorAll('nav a span:not([role=tooltip])')].map(s => s.textContent.trim()).filter(Boolean)
  const icons = aside.querySelectorAll('nav a svg').length
  const dividers = [...aside.querySelectorAll('div')].filter(d => d.offsetHeight <= 2 && d.offsetWidth >= 24).length
  return { width: w, labels, iconCount: icons, dividerCount: dividers }
})()`)

// 2. 悬停第一个导航图标 → tooltip
const navBox = await ev(`(() => {
  const a = document.querySelector('nav a')
  const r = a.getBoundingClientRect()
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) }
})()`)
await hoverAt(navBox.x, navBox.y)
await new Promise((r) => setTimeout(r, 500))
const tip = await ev(`(() => {
  const t = document.querySelector('nav a span[role=tooltip]')
  if (!t) return null
  const s = getComputedStyle(t)
  const r = t.getBoundingClientRect()
  return { text: t.textContent.trim(), opacity: s.opacity, onRight: r.left > 72 }
})()`)
await shot(SHOT_HOVER)

// 3. 点击「报告」验证路由
const clickBox = await ev(`(() => {
  const a = [...document.querySelectorAll('nav a')].find(x => x.querySelector('span[role=tooltip]')?.textContent.trim() === '报告')
  const r = a.getBoundingClientRect()
  return { x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2) }
})()`)
await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: clickBox.x, y: clickBox.y, button: 'left', clickCount: 1 })
await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: clickBox.x, y: clickBox.y, button: 'left', clickCount: 1 })
await new Promise((r) => setTimeout(r, 1200))
const afterClick = await ev(`location.pathname`)

await shot(SHOT)

const out = { rail, tip, afterClick, consoleErrors: errors }
console.log(JSON.stringify(out, null, 2))
ws.close()
chrome.kill()
process.exit(0)
