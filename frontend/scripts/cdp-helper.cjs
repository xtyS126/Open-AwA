/* CDP 辅助脚本：通过 adb forward 的 9222 端口驱动 APP WebView 验证
 * 用法：node scripts/cdp-helper.cjs eval "<js>" | nav <path> | shot <out.png> | url
 * 依赖 ws 包（frontend/node_modules 已内置）
 */
const WebSocket = require('ws')
const http = require('http')
const fs = require('fs')

function getWsUrl() {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:9222/json', (r) => {
      let d = ''
      r.on('data', (c) => (d += c))
      r.on('end', () => {
        try {
          const targets = JSON.parse(d)
          const page = targets.find((t) => t.type === 'page')
          if (!page) return reject(new Error('no page target'))
          resolve(page.webSocketDebuggerUrl)
        } catch (e) { reject(e) }
      })
    }).on('error', reject)
  })
}

async function main() {
  const wsUrl = await getWsUrl()
  const ws = new WebSocket(wsUrl)
  let id = 0
  const pending = new Map()
  ws.on('message', (d) => {
    const m = JSON.parse(d.toString())
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
  })
  await new Promise((r) => ws.on('open', r))
  const cmd = (method, params = {}) => new Promise((r) => {
    const i = ++id
    pending.set(i, r)
    ws.send(JSON.stringify({ id: i, method, params }))
  })

  const arg = process.argv[2]
  try {
    if (arg === 'eval') {
      const expr = process.argv[3]
      const res = await cmd('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
      const r = res.result
      if (r.exceptionDetails) {
        console.log('EXCEPTION: ' + JSON.stringify(r.exceptionDetails.exception?.description || r.exceptionDetails.text))
      } else {
        console.log(JSON.stringify(r.result?.value ?? r.result))
      }
    } else if (arg === 'nav') {
      const path = process.argv[3]
      await cmd('Runtime.evaluate', {
        expression: `history.pushState({}, '', '${path}'); window.dispatchEvent(new PopStateEvent('popstate')); 'ok'`,
        returnByValue: true,
      })
      console.log('navigated to ' + path)
    } else if (arg === 'shot') {
      const out = process.argv[3]
      const res = await cmd('Page.captureScreenshot', { format: 'png' })
      fs.writeFileSync(out, Buffer.from(res.result.data, 'base64'))
      console.log('saved ' + out)
    } else if (arg === 'url') {
      const res = await cmd('Runtime.evaluate', { expression: 'location.pathname', returnByValue: true })
      console.log(res.result.result.value)
    }
  } catch (e) {
    console.error('CDP ERROR: ' + e.message)
    process.exit(1)
  }
  ws.close()
  process.exit(0)
}

main().catch((e) => { console.error(e.message); process.exit(1) })
