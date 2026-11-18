/**
 * 背景 / 图标 / 表格验收（CDP）。
 *
 * 判定：
 * 1. 背景三层齐全：.ambient-base 是渐变、.ambient-arc 至少 2 道且带环比遮罩
 * 2. 图标全部是 url(#icon-grad-*) 描边，且 gradient id 唯一（无重复 id 掉色）
 * 3. 表格行没有分割线（computed border-bottom-width = 0），靠 padding 留白
 * 4. 逐页 0 console error
 *
 * 用法：node frontend/scripts/probe-surface.mjs [baseUrl]
 */
import { spawn } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'

const BASE = (process.argv[2] || 'http://localhost:5173').replace(/\/+$/, '')
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9377
const DIR = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check'
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/surface_profile'
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

await send('Page.navigate', { url: BASE + '/' })
await new Promise((r) => setTimeout(r, 5500))

const ambient = await ev(`(() => {
  const base = document.querySelector('.ambient-base')
  const arcs = [...document.querySelectorAll('.ambient-arc')]
  const orb = [...document.querySelectorAll('.ambient-orb')]
  return {
    baseBg: base ? getComputedStyle(base).backgroundImage.slice(0, 90) : null,
    orbs: orb.length,
    arcs: arcs.map((el) => {
      const cs = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      return {
        size: [Math.round(r.width), Math.round(r.height)],
        mask: (cs.maskImage || cs.webkitMaskImage || '').slice(0, 46),
        blur: cs.filter,
        opacity: cs.opacity,
        arcFrom: cs.getPropertyValue('--arc-from').trim(),
      }
    }),
  }
})()`)

const icons = await ev(`(() => {
  const svgs = [...document.querySelectorAll('svg')].filter((s) => s.querySelector('path[d]') && s.getAttribute('viewBox') === '0 0 24 24')
  const grads = [...document.querySelectorAll('linearGradient')].map((g) => g.id)
  return {
    total: svgs.length,
    gradientStroke: svgs.filter((s) => (s.getAttribute('stroke') || '').startsWith('url(#'))
      .length,
    currentStroke: svgs.filter((s) => s.getAttribute('stroke') === 'currentColor').length,
    gradientIds: grads.length,
    uniqueIds: new Set(grads).size,
    strokeWidths: [...new Set(svgs.map((s) => s.getAttribute('stroke-width')))],
    caps: [...new Set(svgs.map((s) => s.querySelector('path').getAttribute('stroke-linecap')))],
  }
})()`)

const dpr = await ev('window.devicePixelRatio')
await shot('surface-dashboard')

/* 图标特写：把侧边栏裁出来，方便肉眼看渐变有没有出来 */
const sideBox = await ev(`(() => {
  const el = document.querySelector('aside[aria-label="主导航"]')
  const r = el.getBoundingClientRect()
  return { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) }
})()`)
if (sideBox) {
  const res = await send('Page.captureScreenshot', {
    format: 'png',
    clip: { ...sideBox, scale: 2 },
  })
  writeFileSync(`${DIR}/surface-icons.png`, Buffer.from(res.data, 'base64'))
}

/* 表格：确认没有行分割线 */
const tables = []
for (const [path, name, shotName] of [
  ['/tasks', '任务', 'surface-tasks'],
  ['/report', '报告', 'surface-report'],
]) {
  await send('Page.navigate', { url: BASE + path })
  await new Promise((r) => setTimeout(r, 4200))
  const info = await ev(`(() => {
    const t = document.querySelector('table.data-table')
    if (!t) return { table: false }
    const tds = [...t.querySelectorAll('tbody td')]
    const borders = [...new Set(tds.map((td) => getComputedStyle(td).borderBottomWidth))]
    const pads = [...new Set(tds.map((td) => getComputedStyle(td).paddingTop))]
    const first = tds[0]
    return {
      table: true,
      hoverable: t.classList.contains('is-hoverable'),
      rows: t.querySelectorAll('tbody tr').length,
      cellBorderWidths: borders,
      cellPadTop: pads,
      firstCellRadius: first ? getComputedStyle(first).borderTopLeftRadius : null,
      minRowPx: Math.min(...[...t.querySelectorAll('tbody tr')].map((tr) => Math.round(tr.getBoundingClientRect().height))),
    }
  })()`)
  tables.push({ page: path, label: name, ...info })
  await shot(shotName)
}

console.log(JSON.stringify({ dpr, ambient, icons, tables, errors }, null, 2))
chrome.kill()
process.exit(0)
