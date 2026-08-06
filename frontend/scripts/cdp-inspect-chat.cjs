/* 捕获 APP 内 chat 请求 payload，验证 thinking_enabled 实际发送值 */
const WebSocket = require('ws')
const http = require('http')

function getWsUrl() {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:9222/json', (r) => {
      let d = ''
      r.on('data', (c) => (d += c))
      r.on('end', () => resolve(JSON.parse(d).find((t) => t.type === 'page').webSocketDebuggerUrl))
    }).on('error', reject)
  })
}

async function main() {
  const wsUrl = await getWsUrl()
  const ws = new WebSocket(wsUrl)
  let id = 0
  const pending = new Map()
  const requests = []
  ws.on('message', (d) => {
    const m = JSON.parse(d.toString())
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }
    if (m.method === 'Network.requestWillBeSent' && m.params.request.url.includes('/chat')) {
      requests.push({ url: m.params.request.url, postData: m.params.request.postData || null })
    }
  })
  await new Promise((r) => ws.on('open', r))
  const cmd = (method, params = {}) => new Promise((r) => {
    const i = ++id
    pending.set(i, r)
    ws.send(JSON.stringify({ id: i, method, params }))
  })
  await cmd('Network.enable')

  // 发送测试消息
  await cmd('Runtime.evaluate', {
    expression: `(() => {
      const ta = document.querySelector('textarea')
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set
      setter.call(ta, '再测一次思考开关')
      ta.dispatchEvent(new Event('input', { bubbles: true }))
      return 'typed'
    })()`, returnByValue: true,
  })
  await new Promise((r) => setTimeout(r, 500))
  await cmd('Runtime.evaluate', {
    expression: `(() => {
      const btn = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === '发送')
      if (btn) btn.click()
      return 'sent'
    })()`, returnByValue: true,
  })
  await new Promise((r) => setTimeout(r, 4000))
  for (const r of requests) {
    const p = r.postData ? JSON.parse(r.postData) : null
    console.log('URL:', r.url.slice(0, 60))
    console.log('thinking_enabled:', p ? p.thinking_enabled : '(no body)')
    console.log('thinking_depth:', p ? p.thinking_depth : '(no body)')
    console.log('model:', p ? p.model : '(no body)')
  }
  ws.close()
  process.exit(0)
}
main().catch((e) => { console.error(e.message); process.exit(1) })
