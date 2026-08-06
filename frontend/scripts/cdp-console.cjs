/* 抓取 APP WebView 的 console 输出与网络错误 */
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
  const logs = []
  ws.on('message', (d) => {
    const m = JSON.parse(d.toString())
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return }
    if (m.method === 'Runtime.consoleAPICalled') {
      const type = m.params.type
      const text = m.params.args.map(a => a.value || a.description || '').join(' ').slice(0, 200)
      logs.push(`[${type}] ${text}`)
    }
    if (m.method === 'Network.loadingFailed') {
      logs.push(`[NET_FAIL] ${m.params.errorText} url=${(m.params.requestId || '').slice(0, 20)}`)
    }
    if (m.method === 'Log.entryAdded' && m.params.entry.level === 'error') {
      logs.push(`[LOG_ERROR] ${m.params.entry.text.slice(0, 200)}`)
    }
  })
  await new Promise((r) => ws.on('open', r))
  const cmd = (method, params = {}) => new Promise((r) => {
    const i = ++id
    pending.set(i, r)
    ws.send(JSON.stringify({ id: i, method, params }))
  })
  await cmd('Runtime.enable')
  await cmd('Network.enable')
  await cmd('Log.enable')
  // 监听 20 秒（期间会触发 WS 重连尝试）
  await new Promise((r) => setTimeout(r, 20000))
  // 也检查当前 WS 对象状态
  const state = await cmd('Runtime.evaluate', {
    expression: `(() => {
      const dots = [...document.querySelectorAll('[class*=status-dot]')].map(d => (d.className.baseVal || d.className).toString())
      return JSON.stringify({ dots })
    })()`, returnByValue: true,
  })
  console.log('状态点:', state.result?.result?.value)
  console.log('--- 最近日志 ---')
  logs.slice(-25).forEach((l) => console.log(l))
  ws.close()
  process.exit(0)
}
main().catch((e) => { console.error(e.message); process.exit(1) })
