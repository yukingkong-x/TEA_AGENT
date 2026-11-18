/**
 * 实时传感面板验收（CDP）。
 *
 * 判定：
 * 1. 面板存在，卡片数 = 7（6 传感 + 气压）
 * 2. 每张卡有数值（不是全部「—」），且土壤含水率在 0~100
 * 3. 没有 console error / 未捕获异常
 * 4. 出图：整屏 + 面板特写
 *
 * 用法：node frontend/scripts/probe-sensor-panel.mjs [baseUrl]
 */
import { spawn } from 'node:child_process'
import { mkdirSync, rmSync } from 'node:fs'

const BASE = (process.argv[2] || 'http://localhost:5173').replace(/\/+$/, '')
const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9361
const DIR = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check'
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/sensor_profile'
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
await send('DOM.enable')

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
// 模拟器 15 秒一帧：等满两帧，rssi 与 WS 曲线才有内容可验
await new Promise((r) => setTimeout(r, 17000))

const info = await ev(`(() => {
  const panel = document.querySelector('section[aria-label="实时传感器读数"]')
  if (!panel) return { panel: false }
  const cards = [...panel.querySelectorAll('article')].map((a) => ({
    label: a.querySelector('p')?.textContent?.trim(),
    value: a.querySelector('p.num, p .num')?.textContent?.trim(),
    sparkPaths: a.querySelectorAll('svg path').length,
    text: a.innerText.replace(/\\n+/g, ' | ').slice(0, 120),
  }))
  const box = panel.getBoundingClientRect()
  return {
    panel: true,
    cards,
    count: cards.length,
    box: { x: Math.round(box.x), y: Math.round(box.y), w: Math.round(box.width), h: Math.round(box.height) },
    link: panel.querySelector('div.flex.flex-wrap')?.innerText.replace(/\\n+/g, ' '),
    scrollH: document.querySelector('.overflow-auto, .overflow-y-auto')?.scrollHeight ?? null,
  }
})()`)

const shot = async (name, clip) => {
  const res = await send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: false,
    ...(clip ? { clip: { ...clip, scale: 2 } } : {}),
  })
  const { writeFileSync } = await import('node:fs')
  writeFileSync(`${DIR}/${name}.png`, Buffer.from(res.data, 'base64'))
}

await shot('sensor-dashboard')
if (info?.panel) {
  await shot('sensor-panel', {
    x: info.box.x - 4,
    y: info.box.y - 4,
    width: info.box.w + 8,
    height: info.box.h + 8,
  })
}

console.log(JSON.stringify({ ...info, errors }, null, 2))
ws.close()
chrome.kill()
