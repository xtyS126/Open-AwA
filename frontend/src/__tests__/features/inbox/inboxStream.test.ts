import { beforeEach, describe, expect, it, vi } from 'vitest'

let useInboxStore: typeof import('@/features/inbox/store/inboxStore').useInboxStore

vi.mock('@/shared/api/client', () => ({
  API_BASE_URL: '/api',
  getCachedApiKey: () => 'test-token',
  // authStore 依赖 client 的这两个导出（登出清理注册链引入），mock 需补齐
  setUnauthorizedHandler: vi.fn(),
  clearCachedApiKey: vi.fn(),
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}))

class MockBroadcastChannel {
  static instances: MockBroadcastChannel[] = []
  onmessage: ((event: MessageEvent) => void) | null = null

  constructor(_name: string) {
    MockBroadcastChannel.instances.push(this)
  }

  postMessage = vi.fn()
  close = vi.fn()
}

class MockWebSocket {
  static instances: MockWebSocket[] = []
  static readonly OPEN = 1
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  close = vi.fn(() => {
    this.readyState = 3
    this.onclose?.()
  })

  constructor(_url: string, _protocols: string[]) {
    MockWebSocket.instances.push(this)
  }
}

describe('inboxStream 跨标签协调', () => {
  beforeEach(async () => {
    vi.resetModules()
    MockBroadcastChannel.instances = []
    MockWebSocket.instances = []
    vi.stubGlobal('BroadcastChannel', MockBroadcastChannel)
    vi.stubGlobal('WebSocket', MockWebSocket)
    ;({ useInboxStore } = await import('@/features/inbox/store/inboxStore'))
    useInboxStore.getState().resetForLogout()
  })

  it('在更小的远程标签加入后释放本地领导连接', async () => {
    const stream = await import('@/features/inbox/inboxStream')

    stream.connectInboxStream()
    expect(MockWebSocket.instances).toHaveLength(1)

    const channel = MockBroadcastChannel.instances[0]
    channel.onmessage?.({
      data: { type: 'presence', tabId: '0000', active: true, timestamp: Date.now() },
    } as MessageEvent)

    expect(MockWebSocket.instances[0].close).toHaveBeenCalledTimes(1)
    expect(useInboxStore.getState().streamStatus).toBe('connecting')
    stream.disconnectInboxStream()
  })

  it('从领导标签接收广播通知而不建立第二条连接', async () => {
    const stream = await import('@/features/inbox/inboxStream')

    stream.connectInboxStream()
    const channel = MockBroadcastChannel.instances[0]
    channel.onmessage?.({
      data: { type: 'presence', tabId: '0000', active: true, timestamp: Date.now() },
    } as MessageEvent)
    channel.onmessage?.({
      data: {
        type: 'message',
        tabId: '0000',
        raw: JSON.stringify({
          id: 'message-1',
          title: '通知',
          content: '跨标签通知',
          category: 'notification',
          read: false,
          action_url: null,
          action_label: null,
          created_at: '2026-07-27T00:00:00Z',
        }),
      },
    } as MessageEvent)

    expect(MockWebSocket.instances).toHaveLength(1)
    expect(useInboxStore.getState().messages.map((message) => message.id)).toEqual(['message-1'])
    stream.disconnectInboxStream()
  })
})
