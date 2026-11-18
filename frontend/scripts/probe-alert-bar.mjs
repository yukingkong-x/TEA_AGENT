/**
 * 总控页告警条验收（单条 + 下拉收纳 + 一键清除）：
 * 1. 折叠态只有 1 条 role="alert"（严重度最高那条），其余收进「还有 N 条」
 * 2. 展开后浮层用 alert-pop 120ms 淡入，条目数与后端未确认数一致
 * 3. Esc / 点浮层外部都能收起
 * 4. 浮层内单条「确认」→ 计数 -1
 * 5. 「一键清除」→ 二次确认 → 告警条整体消失（空态不渲染）
 * 6. 0 console error
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { spawn } from 'node:child_process'

const BASE = process.argv[2] ?? 'http://localhost:5173'
const SHOT_DIR = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/alert'
mkdirSync(SHOT_DIR, { recursive: true })
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9391
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/alert_profile'

const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--window-size=1440,1000', 'about:blank'], { stdio: 'ignore' })

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
const wait = (ms) => new Promise((r) => setTimeout(r, ms))
const shot = async (name, height = 1000) => {
  const cap = await send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: 1440, height, scale: 1 } })
  writeFileSync(`${SHOT_DIR}/${name}.png`, Buffer.from(cap.data, 'base64'))
}

await send('Runtime.enable'); await send('Log.enable'); await send('Page.enable')
await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false })
await send('Page.navigate', { url: BASE })
await wait(9000)

const HELPERS = `
  const text = (el) => el?.textContent?.replace(/\\s+/g,' ').trim() ?? ''
  const btn = (t) => [...document.querySelectorAll('button')].find((b) => text(b).startsWith(t))
  const section = () => document.querySelector('section[aria-label="未确认报警"]')
`

const run = async (body) => ev(`(() => {${HELPERS}\n${body}})()`)

const collapsed = await ev(`(() => {${HELPERS}
  const bars = [...document.querySelectorAll('[role="alert"]')]
  const s = section()
  return {
    barCount: bars.length,
    topText: bars[0] ? text(bars[0]) : null,
    hasCriticalChip: bars[0] ? text(bars[0]).startsWith('严重') : false,
    toggle: btn('还有') ? text(btn('还有')) : null,
    hasClearBtn: Boolean(btn('一键清除')),
    panelOpen: Boolean(document.querySelector('#alert-more-panel')),
    sectionHeight: s ? Math.round(s.getBoundingClientRect().height) : 0,
  }
})()`)
await shot('alert-collapsed')

// 展开
await run(`btn('还有').click()`)
await wait(260)
const opened = await ev(`(() => {${HELPERS}
  const panel = document.querySelector('#alert-more-panel')
  if (!panel) return { panelOpen: false }
  const cs = getComputedStyle(panel)
  const rows = [...panel.querySelectorAll('li')].map((li) => text(li))
  const rect = panel.getBoundingClientRect()
  return {
    panelOpen: true,
    animationName: cs.animationName,
    animationDuration: cs.animationDuration,
    opacity: Number(cs.opacity).toFixed(2),
    rows,
    rowCount: rows.length,
    ackedLeftOf: Math.round(rect.left),
    belowBar: Math.round(rect.top) > Math.round(section().getBoundingClientRect().bottom) - 1,
    footer: text(panel.querySelector('p[class*="border-t"]')) || null,
  }
})()`)
await shot('alert-expanded', 1140)

// Esc 收起
await ev(`window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))`)
await wait(200)
const afterEsc = await ev(`Boolean(document.querySelector('#alert-more-panel'))`)

// 点外部收起
await run(`btn('还有').click()`)
await wait(220)
await ev(`document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))`)
await wait(200)
const afterOutside = await ev(`Boolean(document.querySelector('#alert-more-panel'))`)

// 浮层里单条确认
await run(`btn('还有').click()`)
await wait(220)
const beforeAck = await ev(`(() => {${HELPERS} return { toggle: text(btn('还有')), firstRow: text(document.querySelector('#alert-more-panel li')) } })()`)
await run(`const row = document.querySelector('#alert-more-panel li')
  const b = [...row.querySelectorAll('button')].find((x) => text(x) === '确认')
  b.click()`)
await wait(700)
const afterAck = await ev(`(() => {${HELPERS}
  const panel = document.querySelector('#alert-more-panel')
  return { toggle: btn('还有') ? text(btn('还有')) : null, rowCount: panel ? panel.querySelectorAll('li').length : 0, panelOpen: Boolean(panel) }
})()`)

// Esc 收起后一键清除 → 二次确认
await ev(`window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))`)
await wait(150)
await run(`btn('一键清除').click()`)
await wait(300)
const confirmState = await ev(`(() => {
  const dlg = document.querySelector('[role="dialog"]')
  const t = (el) => el?.textContent?.replace(/\\s+/g,' ').trim() ?? ''
  return { dialogOpen: Boolean(dlg), title: dlg ? t(dlg.querySelector('h2')) : null, body: dlg ? t(dlg.querySelector('p')) : null }
})()`)
await shot('alert-confirm', 1000)

await ev(`(() => {
  const t = (el) => el?.textContent?.replace(/\\s+/g,' ').trim() ?? ''
  const b = [...document.querySelectorAll('[role="dialog"] button')].find((x) => t(x) === '全部确认')
  b.click()
})()`)
await wait(900)
const cleared = await ev(`(() => {${HELPERS}
  return {
    bars: document.querySelectorAll('[role="alert"]').length,
    sectionExists: Boolean(section()),
    panelExists: Boolean(document.querySelector('#alert-more-panel')),
    dialogExists: Boolean(document.querySelector('[role="dialog"]')),
  }
})()`)
await shot('alert-cleared')

console.log(JSON.stringify({ collapsed, opened, afterEsc, afterOutside, beforeAck, afterAck, confirmState, cleared, errors: errors.slice(0, 5) }, null, 2))
console.log('console errors:', errors.length)

ws.close(); chrome.kill(); process.exit(0)
