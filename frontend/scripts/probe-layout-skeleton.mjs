/**
 * 卡片排版骨架验收（对齐 demo 布局）：
 * 1. 所有卡等高（同行卡片 rect 高度差 < 4px）
 * 2. 小卡数字 33px / 主卡 40px
 * 3. 图形区固定档位：小卡趋势 148px、主卡 196px、spark 50px，且贴卡片底边
 * 4. 湿度卡有露点/VPD 胶囊在数字行右侧；气压卡有 3h 变压胶囊（数据不足时允许缺）
 * 5. 土温/湿度卡有图例
 * 6. 真实鼠标拖拽换主卡回归：黄色跟随主卡槽
 */
import { mkdirSync } from 'node:fs'
import { spawn } from 'node:child_process'

const BASE = process.argv[2] ?? 'http://localhost:5173'
const SHOT_DIR = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check'
mkdirSync(SHOT_DIR, { recursive: true })

const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9377
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/layout_profile'
spawn(CHROME, [
  '--headless=new', '--disable-gpu', '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1440,1400', 'about:blank',
], { stdio: 'ignore' })

await new Promise((r) => setTimeout(r, 2500))
const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()
const page = list.find((i) => i.type === 'page')
const ws = new WebSocket(page.webSocketDebuggerUrl)
let id = 0
const pend = new Map()
const send = (m, p) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method: m, params: p })) })
ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id) } }
await new Promise((r) => ws.onopen = r)
const ev = async (ex) => (await send('Runtime.evaluate', { awaitPromise: true, returnByValue: true, expression: ex })).result?.value
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

await send('Page.enable')
await send('Page.navigate', { url: BASE })
await sleep(9000)

const shot = async (name) => {
  const cap = await send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: 1440, height: 1400, scale: 1 } })
  const { writeFileSync } = await import('node:fs')
  writeFileSync(`${SHOT_DIR}/${name}.png`, Buffer.from(cap.data, 'base64'))
}

const checks = await ev(`(() => {
  const panel = document.querySelector('section[aria-label="实时传感器读数"]')
  if (!panel) return { fatal: 'panel not found' }
  const cards = [...panel.querySelectorAll('article')]
  const byLabel = (l) => cards.find((a) => a.getAttribute('aria-label')?.startsWith(l))
  const rectOf = (a) => a?.getBoundingClientRect()
  const hero = cards.find((a) => rectOf(a).width > rectOf(cards[1]).width + 40)
  const r = (a) => a ? Math.round(rectOf(a).height) : null
  const numSize = (a) => {
    const s = [...a.querySelectorAll('.num')].find((x) => /^\d|^[—]/.test(x.textContent.trim()) && parseFloat(getComputedStyle(x).fontSize) > 24)
    return s ? Math.round(parseFloat(getComputedStyle(s).fontSize)) : null
  }
  const chartH = (a) => {
    const svg = a.querySelector('svg')
    return svg ? Math.round(svg.getBoundingClientRect().height) : null
  }
  const bottomGap = (a) => {
    const aR = rectOf(a); let deepest = 0
    for (const el of a.querySelectorAll('svg, .dli-track, div[class*="bft"], [class*="flex gap-[2px]"]')) {
      const b = el.getBoundingClientRect?.(); if (b) deepest = Math.max(deepest, b.bottom)
    }
    return Math.round(aR.bottom - deepest)
  }
  const pills = (a) => [...a.querySelectorAll('span')].filter((s) => /露点|VPD|3h/.test(s.textContent) && getComputedStyle(s).borderRadius === '9999px').map((s) => s.textContent.trim())
  const legend = (a) => [...a.querySelectorAll('div')].some((d) => d.className.includes('text-[10px]') && d.textContent.includes('露点'))
  const legendSoil = (a) => [...a.querySelectorAll('div')].some((d) => d.className.includes('text-[10px]') && d.textContent.includes('土壤温度') && d.textContent.includes('空气温度'))
  return {
    count: cards.length,
    heroLabel: hero?.getAttribute('aria-label'),
    heights: cards.map(r),
    heightSpread: Math.max(...cards.map(r)) - Math.min(...cards.map(r)),
    smallNumSize: numSize(byLabel('气温')),
    heroNumSize: numSize(hero),
    smallChartH: chartH(byLabel('气压')),
    heroChartH: chartH(hero),
    windSparkH: chartH(byLabel('风速')),
    bottomGaps: cards.map((a) => [a.getAttribute('aria-label')?.slice(0, 3), bottomGap(a)]),
    humPills: pills(byLabel('空气湿度')),
    presPill: pills(byLabel('气压')),
    dewLegend: legend(byLabel('空气湿度')),
    soilLegend: legendSoil(byLabel('土壤温度')),
    errors: (window.__errs || []).length,
  }
})()`)

console.log(JSON.stringify(checks, null, 2))
await shot('layout-default')

/* --- 拖拽换主卡回归 --- */
const grid = await ev(`(() => {
  const panel = document.querySelector('section[aria-label="实时传感器读数"]')
  const cards = [...panel.querySelectorAll('article')]
  const hero = cards.find((a) => a.getBoundingClientRect().width > cards[1].getBoundingClientRect().width + 40)
  const temp = cards.find((a) => a.getAttribute('aria-label')?.startsWith('气温'))
  return {
    heroBox: hero.getBoundingClientRect().toJSON(),
    tempBox: temp.getBoundingClientRect().toJSON(),
  }
})()`)

const drag = async (from, to) => {
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: from.x, y: from.y, button: 'left', clickCount: 1 })
  for (let i = 1; i <= 12; i++) {
    await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: from.x + ((to.x - from.x) * i) / 12, y: from.y + ((to.y - from.y) * i) / 12, button: 'left' })
    await sleep(30)
  }
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: to.x, y: to.y, button: 'left' })
}
await drag({ x: grid.tempBox.x + 60, y: grid.tempBox.y + 30 }, { x: grid.heroBox.x + 60, y: grid.heroBox.y + 30 })
await sleep(1500)

const swap = await ev(`(() => {
  const panel = document.querySelector('section[aria-label="实时传感器读数"]')
  const cards = [...panel.querySelectorAll('article')]
  const hero = cards.find((a) => a.getBoundingClientRect().width > cards[1].getBoundingClientRect().width + 40)
  const num = [...hero.querySelectorAll('.num')].find((x) => parseFloat(getComputedStyle(x).fontSize) > 24)
  return {
    heroLabel: hero.getAttribute('aria-label')?.slice(0, 4),
    numColor: getComputedStyle(num).color,
    heroNumSize: Math.round(parseFloat(getComputedStyle(num).fontSize)),
  }
})()`)
console.log('after-swap:', JSON.stringify(swap))
await shot('layout-swapped')

ws.close()
process.exit(0)
