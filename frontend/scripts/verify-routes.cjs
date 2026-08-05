/* 批量验证 APP 内所有路由可访问（无错误边界、页面有实际内容）
 * 用法：node scripts/verify-routes.cjs（需先 adb forward tcp:9222 webview_devtools_remote_<pid>）
 */
const WebSocket = require('ws')
const http = require('http')

const ROUTES = [
  '/chat', '/dashboard', '/settings', '/skills', '/skills/market',
  '/scheduled-tasks', '/plugins/manage', '/memory', '/experience',
  '/billing', '/user', '/user-profile', '/workspace', '/coding',
  '/inbox', '/roles', '/role-market', '/tts', '/im', '/workflows',
  '/subagents', '/vibe-coding', '/discussions', '/pets',
]

function getWsUrl() {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:9222/json', (r) => {
      let d = ''
      r.on('data', (c) => (d += c))
      r.on('end', () => {
        const page = JSON.parse(d).find((t) => t.type === 'page')
        resolve(page.webSocketDebuggerUrl)
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
  const evalJs = async (expr) => {
    const res = await cmd('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
    return res.result?.result?.value
  }

  const results = []
  for (const route of ROUTES) {
    await evalJs(`history.pushState({}, '', '${route}'); window.dispatchEvent(new PopStateEvent('popstate'))`)
    await new Promise((r) => setTimeout(r, 2500))
    const state = await evalJs(`JSON.stringify({
      url: location.pathname,
      hasAlert: !!document.querySelector('[role=alert]'),
      textLen: document.body.innerText.length,
      title: document.querySelector('h1,h2')?.textContent?.slice(0, 30) || '',
    })`)
    const s = JSON.parse(state || '{}')
    const ok = s.url === route && !s.hasAlert && s.textLen > 100
    results.push({ route, ok, title: s.title, textLen: s.textLen, url: s.url })
    console.log(`${ok ? 'OK ' : 'FAIL'} ${route}  title="${s.title}" len=${s.textLen}`)
  }

  const failed = results.filter((r) => !r.ok)
  console.log(`\n=== 结果: ${results.length - failed.length}/${results.length} 通过 ===`)
  if (failed.length) {
    failed.forEach((f) => console.log(`  失败 ${f.route} url=${f.url} len=${f.textLen}`))
  }
  ws.close()
  process.exit(failed.length ? 2 : 0)
}
main().catch((e) => { console.error(e.message); process.exit(1) })
