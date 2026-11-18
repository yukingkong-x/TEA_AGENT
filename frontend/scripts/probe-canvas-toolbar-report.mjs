/**
 * 画布工具栏 + 报告日报排版 + 运行收尾对账 验收：
 * 1. 画布底部工具栏按钮不再竖排换行（每个按钮高度 ≈ 单行）
 * 2. 画布载入后对账最近 run：note 显示「最近 run #N 已结束」，无残留执行光斑
 * 3. 报告页日报：不出现原始 **、>、|---| 记号；表格渲染成真 table
 * 4. 0 console error
 */
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { spawn } from 'node:child_process'

const BASE = process.argv[2] ?? 'http://localhost:5173'
const SHOT_DIR = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/canvas-toolbar'
mkdirSync(SHOT_DIR, { recursive: true })
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9409
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/ct_profile'
rmSync(profile, { recursive: true, force: true })

const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, '--no-first-run', '--hide-crash-restore-bubble',
  '--window-size=1440,1000', 'about:blank'], { stdio: 'ignore' })

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

// ── 画布页 ──
await send('Page.navigate', { url: `${BASE}/canvas` })
await wait(9000)

const toolbar = await ev(`(() => {
  const bar = [...document.querySelectorAll('div')].find((d) => d.className?.includes?.('bottom-4') && d.querySelector('button'))
  if (!bar) return { found: false }
  const btns = [...bar.querySelectorAll('button')].map((b) => {
    const r = b.getBoundingClientRect()
    return { text: b.textContent.replace(/\\s+/g, '').trim(), h: Math.round(r.height), w: Math.round(r.width) }
  })
  return {
    found: true,
    btns,
    maxBtnH: Math.max(...btns.map((b) => b.h)),
    wrapped: btns.some((b) => b.h > 60),
  }
})()`)
console.log('TOOLBAR', JSON.stringify(toolbar))
await shot('canvas-toolbar', 620)

const canvasState = await ev(`(() => {
  const note = [...document.querySelectorAll('p,span')].map((e) => e.textContent).find((t) => t && t.includes('最近 run'))
  const glowing = [...document.querySelectorAll('.react-flow__node')].filter((n) => n.textContent && /执行中/.test(n.textContent)).length
  return { note: note ?? null, glowingNodes: glowing }
})()`)
console.log('CANVAS_STATE', JSON.stringify(canvasState))

// ── 报告页：日报排版 ──
await send('Page.navigate', { url: `${BASE}/report` })
await wait(9000)

const daily = await ev(`(() => {
  const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('生成日报'))
  if (btn) btn.click()
  return true
})()`)
await wait(2500)
const mdCheck = await ev(`(() => {
  const raw = document.body.innerText
  const hasStars = /\\*\\*/.test(raw)
  const hasPipeTable = /\\|\\s*-{2,}/.test(raw)
  const hasQuoteMark = /\\n>\\s/.test(raw) || raw.includes('> run #')
  const tables = document.querySelectorAll('table').length
  const bolds = [...document.querySelectorAll('strong')].length
  const quotes = [...document.querySelectorAll('blockquote')].length
  const lists = [...document.querySelectorAll('ul,ol')].length
  return { hasStars, hasPipeTable, hasQuoteMark, tables, bolds, quotes, lists }
})()`)
console.log('DAILY_MD', JSON.stringify(mdCheck))
await shot('report-daily', 1400)

chrome.kill()
console.log('ERRORS', errors.length, errors.slice(0, 5))
