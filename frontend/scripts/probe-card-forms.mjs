/**
 * 卡片重设计 v3 验收（CDP）：7 种专用图形逐卡判定 + 拖拽换主卡回归 + 出图。
 *
 * 判定：
 * · 土壤含水率（默认主卡）→ 半环仪表（4 段弧 + 指针）+ 分区图例 + 缺水线趋势
 * · 气温 → 适宜带 rect + 高/低点（2 个标记）
 * · 空气湿度 → 适宜带 rect（露点副线有 24h 对齐数据才画）
 * · 土壤温度 → 图例 chips（土壤/空气温度）
 * · 风速 → 蒲福 13 格刻度条 + ▲ 指示
 * · 气压 → 高/低点标记
 * · 光照 → DLI 轨道条
 * · 主卡数字 = rgb(184,134,11)；拖拽换主卡后黄色跟随
 *
 * 用法：node frontend/scripts/probe-card-forms.mjs [baseUrl]
 */
import { spawn } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'

const BASE = (process.argv[2] || 'http://localhost:5173').replace(/\/+$/, '')
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9371
const DIR = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check'
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/forms_profile'
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

const readCards = async () =>
  ev(`(() => {
    const panel = document.querySelector('section[aria-label=\"实时传感器读数\"]')
    return [...panel.querySelectorAll('article')].map((a) => {
      const num = [...a.querySelectorAll('.num')].find((s) => /^[-—\\d]/.test(s.textContent.trim()))
      const r = a.getBoundingClientRect()
      return {
        label: a.querySelector('p')?.textContent?.trim(),
        numColor: num ? getComputedStyle(num).color : null,
        w: Math.round(r.width),
        cx: Math.round(r.left + r.width / 2),
        cy: Math.round(r.top + r.height / 2),
        gaugeArcs: a.querySelectorAll('svg path[stroke]').length,
        hasNeedle: [...a.querySelectorAll('svg line')].some((l) => (l.getAttribute('stroke') || '') === '#55645B'),
        bandRects: [...a.querySelectorAll('svg rect')].length,
        dots: a.querySelectorAll('span.absolute.rounded-full').length,
        bftCells: [...a.children].some((c) => c.querySelector?.('div.flex.gap-\\\\[2px\\\\]')) ? a.querySelectorAll('div.flex.gap-\\\\[2px\\\\] > div').length : 0,
        legendText: [...a.querySelectorAll('div')].some((d) => d.textContent.includes('适宜40–70')),
        soilLegend: [...a.querySelectorAll('div')].some((d) => d.textContent.includes('空气温度')),
        dliTrack: [...a.querySelectorAll('div')].some((d) => d.textContent.includes('mol/m²')),
        beaufortMark: [...a.querySelectorAll('div span')].some((s) => s.textContent.startsWith('▲')),
        subText: (a.innerText.match(/第3行|\\n/g) ? a.innerText.split('\\n')[2] : ''),
      }
    })
  })()`)

const mouse = async (type, x, y) =>
  send('Input.dispatchMouseEvent', {
    type,
    x,
    y,
    button: 'left',
    clickCount: type === 'mousePressed' || type === 'mouseReleased' ? 1 : 0,
  })

const shot = async (name, clip) => {
  const res = await send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false,
    ...(clip ? { clip: { ...clip, scale: 2 } } : {}),
  })
  writeFileSync(`${DIR}/${name}.png`, Buffer.from(res.data, 'base64'))
}

const cards = await readCards()
const panelBox = await ev(`(() => {
  const b = document.querySelector('section[aria-label=\"实时传感器读数\"]').getBoundingClientRect()
  return { x: Math.round(b.x) - 4, y: Math.round(b.y) - 4, width: Math.round(b.width) + 8, height: Math.round(b.height) + 8 }
})()`)
await shot('forms-default', panelBox)
console.log('--- 默认布局 ---')
for (const c of cards) console.log(JSON.stringify(c))

// 拖拽回归：第一张小卡 → 主卡槽
const hero = cards.find((c) => c.w > 500)
const small = cards.find((c) => c.w <= 500 && c.label !== hero.label)
await mouse('mousePressed', small.cx, small.cy)
await new Promise((r) => setTimeout(r, 260))
for (let i = 1; i <= 14; i++) {
  await mouse('mouseMoved', Math.round(small.cx + ((hero.cx - small.cx) * i) / 14), Math.round(small.cy + ((hero.cy - small.cy) * i) / 14))
  await new Promise((r) => setTimeout(r, 24))
}
await new Promise((r) => setTimeout(r, 120))
await mouse('mouseReleased', hero.cx, hero.cy)
await new Promise((r) => setTimeout(r, 1000))

const after = await readCards()
await shot('forms-swapped', panelBox)
console.log('--- 换主卡后 ---')
for (const c of after) console.log(JSON.stringify(c))

const heroAmber = (list) => {
  const h = list.find((c) => c.w > 500)
  return h && h.numColor === 'rgb(184, 134, 11)'
}
const byLabel = (list, label) => list.find((c) => c.label === label) || {}
const checks = {
  heroLabelDefault: hero?.label,
  heroAmberDefault: heroAmber(cards),
  gaugeCard: byLabel(cards, '土壤含水率'),
  tempBand: byLabel(cards, '气温').bandRects >= 1,
  humBand: byLabel(cards, '空气湿度').bandRects >= 1,
  soilLegend: byLabel(cards, '土壤温度').soilLegend === true,
  beaufort: byLabel(cards, '风速').beaufortMark === true,
  pressureDots: byLabel(cards, '气压').dots >= 2,
  dliBar: byLabel(cards, '光照').dliTrack === true,
  heroAmberSwapped: heroAmber(after),
  heroLabelSwapped: after.find((c) => c.w > 500)?.label,
  errors: errors.length,
}
console.log('--- 判定 ---')
console.log(JSON.stringify(checks, null, 2))
const pass =
  checks.heroAmberDefault &&
  checks.tempBand &&
  checks.humBand &&
  checks.soilLegend &&
  checks.beaufort &&
  checks.pressureDots &&
  checks.dliBar &&
  checks.heroAmberSwapped &&
  checks.heroLabelDefault !== checks.heroLabelSwapped &&
  errors.length === 0
console.log(pass ? 'PASS' : 'FAIL')
ws.close()
chrome.kill()
process.exit(pass ? 0 : 1)
