/* CDP 性能采样：JS 时间、DOM 节点数、渲染循环检查 */
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

  // 1. 页面状态：DOM 节点数、事件监听器数量、动画数量
  const dom = await evalJs(`(() => {
    const anims = document.getAnimations()
    return JSON.stringify({
      nodeCount: document.getElementsByTagName('*').length,
      animCount: anims.length,
      animNames: anims.slice(0, 10).map(a => a.animationName || a.id || a.constructor.name),
      listeners: performance.getEntriesByType('event').length,
    })
  })()`)
  console.log('DOM/动画:', dom)

  // 2. 计算性能指标
  await cmd('Performance.enable')
  await new Promise((r) => setTimeout(r, 3000))
  const metrics = await cmd('Performance.getMetrics')
  const m = {}
  metrics.result.metrics.forEach((x) => { m[x.name] = x.value })
  console.log('JS 耗时(s):', {
    script: m.ScriptDuration?.toFixed(2),
    layout: m.LayoutDuration?.toFixed(2),
    recalcStyle: m.RecalcStyleDuration?.toFixed(2),
    taskDuration: m.TaskDuration?.toFixed(2),
    tasks: m.TaskCount,
    jsHeap: (m.JSHeapUsedSize / 1048576).toFixed(1) + 'MB',
  })

  // 3. 事件循环延迟（long task 观察 10 秒）
  await cmd('Runtime.evaluate', {
    expression: `(() => {
      window.__longTasks = []
      const obs = new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          window.__longTasks.push({ dur: Math.round(e.duration), start: Math.round(e.startTime) })
        }
      })
      obs.observe({ entryTypes: ['longtask'] })
      return 'observer-set'
    })()`, returnByValue: true,
  })
  await new Promise((r) => setTimeout(r, 10000))
  const longTasks = await evalJs('JSON.stringify(window.__longTasks.slice(0, 15))')
  console.log('10s 内 long tasks:', longTasks || '[]')

  ws.close()
  process.exit(0)
}
main().catch((e) => { console.error(e.message); process.exit(1) })
