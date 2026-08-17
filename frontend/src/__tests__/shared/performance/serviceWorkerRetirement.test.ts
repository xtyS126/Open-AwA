import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it, vi } from 'vitest'

const workerPath = resolve(process.cwd(), 'public/sw.js')
const indexPath = resolve(process.cwd(), 'index.html')
const retiredCacheName = 'anime-blog-v4'

type LifecycleHandler = (event: { waitUntil(task: Promise<unknown>): void }) => void

function loadWorkerHandlers() {
  expect(existsSync(workerPath), '必须提供 /sw.js 主动退役历史 Service Worker').toBe(true)

  const handlers = new Map<string, LifecycleHandler>()
  const skipWaiting = vi.fn(async () => undefined)
  const unregister = vi.fn(async () => true)
  const navigate = vi.fn(async (_url: string) => undefined)
  const windowClients = [
    { url: 'http://localhost:5173/chat', navigate },
    { url: 'http://localhost:5173/settings', navigate },
  ]
  const clients = {
    matchAll: vi.fn(async () => windowClients),
  }
  const cacheStorage = {
    keys: vi.fn(async () => [retiredCacheName, 'unrelated-cache']),
    delete: vi.fn(async (_name: string) => true),
  }
  const registration = { unregister }
  const workerScope = {
    addEventListener: vi.fn((eventName: string, handler: LifecycleHandler) => {
      handlers.set(eventName, handler)
    }),
    skipWaiting,
    clients,
    registration,
  }

  const workerSource = readFileSync(workerPath, 'utf8')
  const executeWorker = new Function(
    'self',
    'caches',
    'clients',
    'registration',
    'skipWaiting',
    workerSource,
  )
  executeWorker(workerScope, cacheStorage, clients, registration, skipWaiting)

  return {
    cacheStorage,
    clients,
    handlers,
    navigate,
    registration,
    skipWaiting,
    windowClients,
  }
}

async function dispatchLifecycle(handler: LifecycleHandler | undefined) {
  expect(handler, '退役 worker 必须注册对应生命周期处理器').toBeTypeOf('function')

  const pendingTasks: Promise<unknown>[] = []
  handler?.({
    waitUntil(task) {
      pendingTasks.push(Promise.resolve(task))
    },
  })
  await Promise.all(pendingTasks)
}

function findLocalhostRetirementScript(html: string) {
  const inlineScripts = Array.from(html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi))
  return inlineScripts.find((match) => {
    const source = match[1]
    return source.includes('localhost')
      && source.includes('serviceWorker')
      && source.includes(retiredCacheName)
  })
}

describe('历史 Service Worker 退役', () => {
  it('安装和激活时立即接管并清理旧缓存、注销自身、刷新窗口客户端', async () => {
    const runtime = loadWorkerHandlers()

    await dispatchLifecycle(runtime.handlers.get('install'))
    expect(runtime.skipWaiting).toHaveBeenCalledTimes(1)

    await dispatchLifecycle(runtime.handlers.get('activate'))
    expect(runtime.cacheStorage.delete).toHaveBeenCalledWith(retiredCacheName)
    expect(runtime.cacheStorage.delete).toHaveBeenCalledTimes(1)
    expect(runtime.cacheStorage.delete).not.toHaveBeenCalledWith('unrelated-cache')
    expect(runtime.registration.unregister).toHaveBeenCalledTimes(1)
    expect(runtime.clients.matchAll).toHaveBeenCalled()
    for (const client of runtime.windowClients) {
      expect(runtime.navigate).toHaveBeenCalledWith(client.url)
    }
  })

  it('在应用入口执行前为 localhost 页面提供注销和旧缓存清理兜底', () => {
    const html = readFileSync(indexPath, 'utf8')
    const entryIndex = html.indexOf('<script type="module" src="/src/main.tsx"></script>')
    const fallbackScript = findLocalhostRetirementScript(html)

    expect(entryIndex, 'index.html 必须包含 /src/main.tsx 入口脚本').toBeGreaterThanOrEqual(0)
    expect(fallbackScript, 'index.html 必须包含仅用于 localhost 的 Service Worker 退役兜底脚本')
      .toBeDefined()
    expect(fallbackScript?.index ?? Number.POSITIVE_INFINITY)
      .toBeLessThan(entryIndex)

    const fallbackSource = fallbackScript?.[1] ?? ''
    expect(fallbackSource).toMatch(/\.getRegistrations\s*\(/)
    expect(fallbackSource).toMatch(/\.unregister\s*\(/)
    expect(fallbackSource).toMatch(/caches\.delete\s*\(/)
    expect(fallbackSource).toContain(retiredCacheName)
    expect(fallbackSource).toContain('navigator.serviceWorker.controller')
    expect(fallbackSource).toContain('sessionStorage')
    expect(fallbackSource).toMatch(/location\.reload\s*\(/)
  })
})
