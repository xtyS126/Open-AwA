/* 逐路由验证：页面空闲后不应有任何 running 的 CSS 动画（WebView 卡死根因防护） */
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
      r.on('end', () => resolve(JSON.parse(d).find((t) => t.type === 'page').webSocketDebuggerUrl))
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

  let failed = 0
  for (const route of ROUTES) {
    await evalJs(`history.pushState({}, '', '${route}'); window.dispatchEvent(new PopStateEvent('popstate'))`)
    // 等待页面加载完成（骨架屏动画结束后 3 秒）
    await new Promise((r) => setTimeout(r, 4000))
    const state = await evalJs(`(() => {
      const anims = document.getAnimations().filter(a => a.playState === 'running')
      return JSON.stringify({
        url: location.pathname,
        running: anims.map(a => (a.animationName || a.id || '').slice(0, 30)),
        count: anims.length,
      })
    })()`)
    const s = JSON.parse(state || '{}')
    const ok = s.url === route && s.count === 0
    if (!ok) failed++
    console.log(`${ok ? 'OK  ' : 'FAIL'} ${route}  running_anims=${s.count}${s.running?.length ? ' ' + JSON.stringify(s.running) : ''}`)
  }
  console.log(`\n=== 结果: ${ROUTES.length - failed}/${ROUTES.length} 路由空闲零动画 ===`)
  ws.close()
  process.exit(failed ? 2 : 0)
}
main().catch((e) => { console.error(e.message); process.exit(1) })
