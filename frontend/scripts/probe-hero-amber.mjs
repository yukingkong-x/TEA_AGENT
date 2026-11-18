/**
 * 主卡颜色验收：只有主卡槽的卡数字/折线是黄色，其余白数字 + 绿折线；
 * 拖一张小卡进主卡槽后黄色跟着走，原主卡变回白/绿。
 *
 * 用法：node frontend/scripts/probe-hero-amber.mjs
 */
import { spawn } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'

const BASE = (process.argv[2] || 'http://localhost:5173').replace(/\/+$/, '')
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9367
const DIR = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check'
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/amber_profile'
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
    '--window-size=1440,1180',
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

await send('Page.navigate', { url: BASE + '/' })
await new Promise((r) => setTimeout(r, 17000))

const readColors = async (tag) => {
  const data = await ev(`(() => {
    const panel = document.querySelector('section[aria-label="实时传感器读数"]')
    const cards = [...panel.querySelectorAll('article')].map((a) => {
      const num = [...a.querySelectorAll('.num')].find((s) => s.textContent.trim() && !s.textContent.includes('较'))
      const line = [...a.querySelectorAll('svg path')].find((p) => (p.getAttribute('stroke') || '').startsWith('#'))
      const r = a.getBoundingClientRect()
      return {
        label: a.querySelector('p')?.textContent?.trim(),
        numColor: num ? getComputedStyle(num).color : null,
        stroke: line ? line.getAttribute('stroke') : null,
        cx: Math.round(r.left + r.width / 2),
        cy: Math.round(r.top + r.height / 2),
        w: Math.round(r.width),
      }
    })
    return cards
  })()`)
  console.log(`--- ${tag} ---`)
  for (const c of data) console.log(`${c.label}: num=${c.numColor} line=${c.stroke} (cx=${c.cx},cy=${c.cy},w=${c.w})`)
  return data
}

const mouse = async (type, x, y) => send('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: type === 'mousePressed' || type === 'mouseReleased' ? 1 : 0 })

const shot = async (name, clip) => {
  const res = await send('Page.captureScreenshot', {
    format: 'png',
    captureBeforeViewport: false,
    captureBeyondViewport: false,
    ...(clip ? { clip: { ...clip, scale: 2 } } : {}),
  })
  writeFileSync(`${DIR}/${name}.png`, Buffer.from(res.data, 'base64'))
}

const before = await readColors('默认布局（soil_moisture 应为主卡=黄，其余=白/绿）')
const hero0 = before.find((c) => c.w > 500) || before[0]
const small0 = before.find((c) => c.w <= 500 && c.label !== hero0.label)
const panelBox = await ev(`(() => {
  const b = document.querySelector('section[aria-label="实时传感器读数"]').getBoundingClientRect()
  return { x: Math.round(b.x) - 4, y: Math.round(b.y) - 4, width: Math.round(b.width) + 8, height: Math.round(b.height) + 8 }
})()`)
await shot('amber-default', panelBox)

// 真实鼠标拖拽：把第一张小卡拖到主卡中心，松手换主卡
await mouse('mousePressed', small0.cx, small0.cy)
await new Promise((r) => setTimeout(r, 260))
const steps = 14
for (let i = 1; i <= steps; i++) {
  await mouse(
    'mouseMoved',
    Math.round(small0.cx + ((hero0.cx - small0.cx) * i) / steps),
    Math.round(small0.cy + ((hero0.cy - small0.cy) * i) / steps),
  )
  await new Promise((r) => setTimeout(r, 24))
}
await new Promise((r) => setTimeout(r, 120))
await shot('amber-mid', panelBox)
await mouse('mouseReleased', hero0.cx, hero0.cy)
await new Promise((r) => setTimeout(r, 900))

const after = await readColors('拖拽换主卡后（黄色应跟随新主卡，原主卡变回白/绿）')
await shot('amber-swapped', panelBox)

const check = (cards) => {
  const hero = cards.find((c) => c.w > 500)
  const smalls = cards.filter((c) => c.w <= 500)
  const amber = (v) => v === 'rgb(184, 134, 11)'
  const paper = (v) => v !== 'rgb(184, 134, 11)'
  const lineAmber = (v) => v === '#C08A12'
  const lineGreen = (v) => v === '#1F7A45'
  return {
    heroLabel: hero?.label,
    heroNumAmber: amber(hero?.numColor),
    heroLineAmber: lineAmber(hero?.stroke),
    smallAllOk: smalls.every((c) => paper(c.numColor) && lineGreen(c.stroke)),
  }
}
const r1 = check(before)
const r2 = check(after)
console.log('--- 判定 ---')
console.log('默认:', JSON.stringify(r1))
console.log('换主卡后:', JSON.stringify(r2))
console.log('errors:', errors.length ? errors : 0)
const pass = r1.heroNumAmber && r1.heroLineAmber && r1.smallAllOk && r2.heroNumAmber && r2.heroLineAmber && r2.smallAllOk && r1.heroLabel !== r2.heroLabel && errors.length === 0
console.log(pass ? 'PASS' : 'FAIL')
ws.close()
chrome.kill()
process.exit(pass ? 0 : 1)
