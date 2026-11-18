/**
 * 画布右侧「运行对话」抽屉验收（CDP 真渲染）
 *
 * 判定项：
 * 1. 抽屉在 /canvas 上存在、宽度约 340、标题显示「运行 #N」
 * 2. 抽屉里有真实消息（来自 /api/runs/{id}），头像是本地立绘、不 broken
 * 3. 「对话」按钮可收起 / 再展开；宽度 400
 * 4. 抽屉展开时画布仍然渲染节点（React Flow 没被挤没），节点数 > 0
 * 5. 全程 0 console error
 */
import { spawn } from 'node:child_process'
import { mkdirSync, rmSync, writeFileSync } from 'node:fs'

const CHROME = 'C:/Users/ye_/AppData/Local/Google/Chrome/Application/chrome.exe'
const PORT = 9393
const SHOTS = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/check'
const profile = 'D:/soft program/school/competitive/TEA_AGENT/_review_frontend/shots/drawer_profile'

rmSync(profile, { recursive: true, force: true })
mkdirSync(profile, { recursive: true })
mkdirSync(SHOTS, { recursive: true })

const chrome = spawn(
  CHROME,
  [
    '--headless=new',
    '--disable-gpu',
    '--hide-scrollbars',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    '--window-size=1520,980',
    'about:blank',
  ],
  { stdio: 'ignore' },
)

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

setTimeout(async () => {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json()
  const page = list.find((item) => item.type === 'page')
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  let id = 0
  const pending = new Map()
  const errors = []
  const send = (method, params) =>
    new Promise((resolve) => {
      const messageId = ++id
      pending.set(messageId, resolve)
      ws.send(JSON.stringify({ id: messageId, method, params }))
    })
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data)
    if (message.method === 'Runtime.exceptionThrown') {
      errors.push(message.params.exceptionDetails.text + (message.params.exceptionDetails.exception?.description ?? ''))
    }
    if (message.method === 'Log.entryAdded' && message.params.entry.level === 'error') {
      errors.push(message.params.entry.text)
    }
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message.result)
      pending.delete(message.id)
    }
  }
  await new Promise((resolve) => (ws.onopen = resolve))
  await send('Runtime.enable')
  await send('Log.enable')
  await send('Page.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: 1520, height: 980, deviceScaleFactor: 1, mobile: false })
  await send('Page.navigate', { url: 'http://localhost:5173/canvas' })
  await sleep(9000)

  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })
    if (result.exceptionDetails) {
      console.log('EVAL ERROR', result.exceptionDetails.text, result.exceptionDetails.exception?.description?.slice(0, 300))
    }
    return result.result?.value
  }

  const before = await evaluate(`(() => {
    const aside = document.querySelector('aside[aria-label="运行对话"]')
    const items = aside ? [...aside.querySelectorAll('ol > li')] : []
    const first = items[0]
    const imgs = aside ? [...aside.querySelectorAll('img')] : []
    const flowNodes = document.querySelectorAll('.react-flow__node')
    const pane = document.querySelector('.react-flow')
    return {
      drawer: Boolean(aside),
      width: aside ? Math.round(aside.getBoundingClientRect().width) : 0,
      header: aside ? aside.querySelector('h2')?.textContent?.trim() : null,
      label: aside ? aside.querySelector('h2 + p, header p')?.textContent?.trim() : null,
      count: items.length,
      firstAgent: first ? first.querySelector('span')?.textContent?.trim() : null,
      firstText: first ? first.querySelectorAll('p')[1]?.textContent?.slice(0, 40) : null,
      toolHints: aside ? [...aside.querySelectorAll('p')].filter((p) => p.textContent.startsWith('工具')).length : 0,
      brokenImgs: imgs.filter((i) => i.complete && i.naturalWidth === 0).length,
      imgs: imgs.length,
      flowNodes: flowNodes.length,
      flowWidth: pane ? Math.round(pane.getBoundingClientRect().width) : 0,
      hasToggle: [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === '对话'),
      handle: Boolean(document.querySelector('[aria-label="拖动调整运行对话宽度"]')),
      text: items.map((i) => i.innerText).join(String.fromCharCode(10)),
      chips: aside ? [...aside.querySelectorAll('li p span')].filter((sp) => /^[\u4e00-\u9fa5]{2,8}$/.test(sp.textContent.trim()) && sp.className.includes('rounded')).length : 0,
    }
  })()`)
  console.log('BEFORE', JSON.stringify(before, null, 2))

  const body = before.text ?? ''
  const fmt = {
    bulletLines: (body.match(/^\s*[-*•·–—+]\s/gm) ?? []).length,
    angleTags: (body.match(/<[^>]{1,20}>/g) ?? []).length,
    middots: (body.match(/·/g) ?? []).length,
    shortRanges: (body.match(/(?<!\d)\d{1,3}-\d{1,3}(?!\d)/g) ?? []).length,
  }
  console.log('FORMAT', JSON.stringify(fmt))

  const shot = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(`${SHOTS}/canvas-drawer.png`, Buffer.from(shot.data, 'base64'))

  // 收起
  await evaluate(`[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === '对话')?.click()`)
  await sleep(700)
  const closed = await evaluate(`(() => {
    const aside = document.querySelector('aside[aria-label="运行对话"]')
    const pane = document.querySelector('.react-flow')
    return { drawer: Boolean(aside), flowWidth: pane ? Math.round(pane.getBoundingClientRect().width) : 0 }
  })()`)
  console.log('CLOSED', JSON.stringify(closed))

  // 再展开
  await evaluate(`[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === '对话')?.click()`)
  await sleep(1200)
  const reopened = await evaluate(`(() => {
    const aside = document.querySelector('aside[aria-label="运行对话"]')
    return { drawer: Boolean(aside), width: aside ? Math.round(aside.getBoundingClientRect().width) : 0 }
  })()`)
  console.log('REOPENED', JSON.stringify(reopened))

  const drag = await evaluate(`(() => {
    const handle = document.querySelector('[aria-label="拖动调整运行对话宽度"]')
    const aside = document.querySelector('aside[aria-label="运行对话"]')
    if (!handle || !aside) return { ok: false }
    const from = Math.round(aside.getBoundingClientRect().width)
    const rect = handle.getBoundingClientRect()
    handle.dispatchEvent(new PointerEvent('pointerdown', { clientX: rect.left + 2, bubbles: true, cancelable: true }))
    window.dispatchEvent(new PointerEvent('pointermove', { clientX: rect.left - 78, bubbles: true }))
    window.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }))
    return { ok: true, from }
  })()`)
  await sleep(500)
  const after = await evaluate(`(() => {
    const aside = document.querySelector('aside[aria-label="运行对话"]')
    return {
      width: aside ? Math.round(aside.getBoundingClientRect().width) : 0,
      saved: Number(window.localStorage.getItem('zhiqiu.canvas.drawerWidth')),
    }
  })()`)
  console.log('DRAG', JSON.stringify({ drag, after }))

  const verdict = {
    '抽屉存在': before.drawer === true,
    '宽度≈480': before.width >= 460 && before.width <= 500,
    '标题是运行 #N': /运行 #\d+|最近一次运行 #\d+/.test(before.label ?? ''),
    '有真实消息': before.count > 0,
    '头像是立绘且不破图': before.imgs > 0 && before.brokenImgs === 0,
    '画布节点仍在': before.flowNodes > 0,
    '开关按钮存在': before.hasToggle === true,
    '收起后抽屉消失': closed.drawer === false,
    '收起后画布变宽': closed.flowWidth > before.flowWidth,
    '再展开恢复': reopened.drawer === true && reopened.width >= 460,
    '无列表符号 - * •': fmt.bulletLines === 0,
    '无尖括号标签': fmt.angleTags === 0,
    '无中点分隔符 ·': fmt.middots === 0,
    '区段无 ASCII 连字符': fmt.shortRanges === 0,
    '段首徽章生效': before.chips >= 3,
    '有宽度拖拽手柄': before.handle === true,
    '可拖到更宽并记住': drag.ok === true && after.width >= drag.from + 60 && after.saved === after.width,
    '0 console error': errors.length === 0,
  }
  console.log('\nRESULT', JSON.stringify(verdict, null, 2))
  if (errors.length) console.log('errors:', errors.slice(0, 5))
  console.log(verdict['抽屉存在'] && verdict['有真实消息'] && verdict['收起后抽屉消失'] && verdict['再展开恢复'] && verdict['0 console error'] ? 'PASS' : 'FAIL')

  ws.close()
  chrome.kill()
  process.exit(0)
}, 2500)
