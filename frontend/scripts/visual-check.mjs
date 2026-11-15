// 一次性 CDP 验收：逐页截图 + 控制台错误 + 文本抽查
import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { setTimeout as sleep } from 'node:timers/promises'

const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const OUT = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check'
const PORT = 9333
const BASE = 'http://localhost:5173'

const pages = [
  { path: '/', grep: ['在线设备', '土壤湿度'] },
  { path: '/canvas', grep: ['保存', '运行', '重新建单'] },
  { path: '/tasks', grep: ['任务号'] },
  { path: '/report', grep: ['基线', '复测', '浇水时长'] },
  // outcome=unverified 那一档：切到没有验证记录的 run，页面必须显示「未产生验证结果」
  {
    path: '/report',
    name: 'report_unverified',
    grep: ['未产生验证结果', '不画 0%'],
    after: `(() => {
      const el = document.getElementById('report-run');
      if (!el) return 'no-select';
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
      setter.call(el, 'run-1003');
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return el.value;
    })()`,
  },
  // outcome=needs_human 那一档：转人工必须说清「不再自动重试」，不能当失败
  {
    path: '/report',
    name: 'report_needs_human',
    grep: ['🚨 转人工', '不再自动重试', '不会'],
    after: `(() => {
      const el = document.getElementById('report-run');
      if (!el) return 'no-select';
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
      setter.call(el, 'run-1002');
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return el.value;
    })()`,
  },
  { path: '/chat', grep: [] },
  { path: '/settings', grep: ['运行模式', '故障注入', '知识库', '调度参数', '智能体'] },
]

mkdirSync(OUT, { recursive: true })
const profile = `${OUT}/profile`
rmSync(profile, { recursive: true, force: true })

const chrome = spawn(CHROME, [
  '--headless=new',
  '--disable-gpu',
  '--hide-scrollbars',
  `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${profile}`,
  '--window-size=1440,1100',
  'about:blank',
], { stdio: 'ignore' })

async function target() {
  for (let i = 0; i < 60; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json`)
      const list = await res.json()
      const page = list.find((item) => item.type === 'page')
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl
    } catch {
      /* 等 chrome 起来 */
    }
    await sleep(250)
  }
  throw new Error('CDP 起不来')
}

const ws = new WebSocket(await target())
await new Promise((resolve) => ws.addEventListener('open', resolve, { once: true }))

let seq = 0
const waiting = new Map()
const logs = []

ws.addEventListener('message', (event) => {
  const msg = JSON.parse(event.data)
  if (msg.id && waiting.has(msg.id)) {
    waiting.get(msg.id)(msg)
    waiting.delete(msg.id)
    return
  }
  if (msg.method === 'Runtime.consoleAPICalled' && ['error', 'warning'].includes(msg.params.type)) {
    logs.push(msg.params.args.map((a) => a.value ?? a.description ?? '').join(' ').slice(0, 300))
  }
  if (msg.method === 'Runtime.exceptionThrown') {
    logs.push(`EXC ${msg.params.exceptionDetails.text} ${msg.params.exceptionDetails.exception?.description ?? ''}`.slice(0, 300))
  }
})

function send(method, params = {}) {
  const id = ++seq
  ws.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve) => waiting.set(id, resolve))
}

await send('Runtime.enable')
await send('Page.enable')

const report = []
for (const item of pages) {
  logs.length = 0
  await send('Page.navigate', { url: BASE + item.path })
  await sleep(2600)
  // 页面内交互（如切 run 下拉）要在滚动与取样之前做
  if (item.after) {
    await send('Runtime.evaluate', { expression: item.after, awaitPromise: true })
    await sleep(900)
  }
  // 滚到底再回顶，触发懒加载
  await send('Runtime.evaluate', {
    expression: `(async () => {
      const h = innerHeight;
      for (let y = 0; y < document.body.scrollHeight; y += h * 0.7) {
        window.scrollTo(0, y);
        await new Promise(r => setTimeout(r, 260));
      }
      window.scrollTo(0, 0);
    })()`,
    awaitPromise: true,
  })
  await sleep(1400)

  const metrics = await send('Runtime.evaluate', {
    expression: `(() => {
      const text = document.body.innerText || '';
      const broken = [...document.images].filter(i => i.complete && i.naturalWidth === 0).length;
      const empty = [...document.images].filter(i => !i.getAttribute('src')).length;
      return JSON.stringify({ len: text.length, broken, empty, text: text.slice(0, 4000) });
    })()`,
    returnByValue: true,
  })
  const data = JSON.parse(metrics.result.result.value)
  const missing = item.grep.filter((word) => !data.text.includes(word))

  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true })
  const file = `${OUT}/${(item.name ?? item.path.replace(/\//g, '_')) || 'root'}.png`
  writeFileSync(file, Buffer.from(shot.result.data, 'base64'))

  report.push({
    path: item.path,
    len: data.len,
    brokenImages: data.broken,
    emptySrc: data.empty,
    missingWords: missing,
    console: [...logs],
    shot: file,
  })
}

writeFileSync(`${OUT}/report.json`, JSON.stringify(report, null, 2))
console.log(JSON.stringify(report.map(({ path, len, brokenImages, emptySrc, missingWords, console: c }) => ({ path, len, brokenImages, emptySrc, missingWords, console: c.slice(0, 6) })), null, 2))

ws.close()
chrome.kill()
