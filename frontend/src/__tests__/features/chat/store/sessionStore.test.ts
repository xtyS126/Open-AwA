import '@testing-library/jest-dom/vitest'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// 使用 vi.hoisted 提前建立 mock 引用
const persistenceMocks = vi.hoisted(() => ({
  loadMessages: vi.fn(),
  saveMessages: vi.fn(() => Promise.resolve()),
  removeMessages: vi.fn(() => Promise.resolve()),
  setActiveSessionId: vi.fn(),
  getActiveSessionId: vi.fn(() => ''),
  getConversationSummaries: vi.fn(() => []),
  setConversationSummaries: vi.fn(),
  isChatPersistenceAvailable: vi.fn(() => true),
}))

vi.mock('@/features/chat/storage/chatPersistence', () => ({
  loadMessages: persistenceMocks.loadMessages,
  saveMessages: persistenceMocks.saveMessages,
  removeMessages: persistenceMocks.removeMessages,
  setActiveSessionId: persistenceMocks.setActiveSessionId,
  getActiveSessionId: persistenceMocks.getActiveSessionId,
  getConversationSummaries: persistenceMocks.getConversationSummaries,
  setConversationSummaries: persistenceMocks.setConversationSummaries,
  isChatPersistenceAvailable: persistenceMocks.isChatPersistenceAvailable,
}))

vi.mock('@/features/chat/store/chatStoreEffects', () => ({
  persistPinnedConversations: vi.fn(),
  persistSelectedModel: vi.fn(),
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
}))

import { useSessionStore } from '@/features/chat/store/sessionStore'
import type { ChatMessage } from '@/features/chat/types'

/** 构造一条消息用于测试 */
function makeMessage(id: string, content: string): ChatMessage {
  return {
    id,
    role: 'user',
    content,
    timestamp: new Date(),
  } as ChatMessage
}

/** 等待所有微任务（loadMessages 的 .then 回调）执行完成 */
async function flushMicrotasks() {
  await new Promise((resolve) => setTimeout(resolve, 0))
}

describe('useSessionStore - setSessionId', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 重置 store 状态
    useSessionStore.setState({
      messages: [],
      sessionId: 'default',
      conversations: [],
      conversationsTotal: 0,
      conversationsHasMore: false,
      pinnedConversations: [],
      conversationsVersion: 0,
      isLoading: false,
      persistenceAvailable: true,
    })
    // 默认 loadMessages 返回空数组
    persistenceMocks.loadMessages.mockResolvedValue([])
  })

  it('setSessionId 不清空现有 messages（保留旧消息）', async () => {
    // 准备：store 中已有旧消息
    const oldMessages = [makeMessage('msg-1', '旧消息1'), makeMessage('msg-2', '旧消息2')]
    useSessionStore.setState({ messages: oldMessages, sessionId: 'old-session' })

    // 默认 loadMessages 返回空数组（模拟新会话无历史）
    persistenceMocks.loadMessages.mockResolvedValue([])

    // 调用 setSessionId 切换到新会话
    useSessionStore.getState().setSessionId('new-session')

    // 立即检查：messages 不应被清空，应保留旧消息直到新数据到达
    expect(useSessionStore.getState().messages).toBe(oldMessages)
    expect(useSessionStore.getState().messages).toHaveLength(2)
    expect(useSessionStore.getState().sessionId).toBe('new-session')

    // 等待异步 loadMessages 完成（返回空数组，不写入 state）
    await flushMicrotasks()

    // 空数组不写入 state（源码：Array.isArray(msgs) && msgs.length > 0），messages 仍保留旧值
    expect(useSessionStore.getState().messages).toBe(oldMessages)
  })

  it('IndexedDB 加载完成后用 loadSequenceNumber 防护写入（旧请求结果不覆盖新请求）', async () => {
    // 准备：旧消息用于验证被新会话数据覆盖
    useSessionStore.setState({
      messages: [makeMessage('old', '旧消息')],
      sessionId: 'old-session',
    })

    // 模拟 A 会话的 loadMessages 返回延迟（用 Promise 控制）
    let resolveA: (value: unknown[]) => void = () => {}
    const loadAPromise = new Promise<unknown[]>((resolve) => {
      resolveA = resolve
    })
    persistenceMocks.loadMessages.mockImplementation((sessionId: string) => {
      if (sessionId === 'session-A') {
        return loadAPromise
      }
      // session-B 立即返回
      return Promise.resolve([makeMessage('msg-B', 'B 会话消息')])
    })

    // 第一次切换到 A（seq=1）
    useSessionStore.getState().setSessionId('session-A')
    // 第二次切换到 B（seq=2，使 seq=1 失效）
    useSessionStore.getState().setSessionId('session-B')

    // B 的 loadMessages 立即 resolve，应写入 state
    await flushMicrotasks()
    expect(useSessionStore.getState().messages).toHaveLength(1)
    expect(useSessionStore.getState().messages[0].id).toBe('msg-B')
    expect(useSessionStore.getState().sessionId).toBe('session-B')

    // 现在 A 的 loadMessages 延迟 resolve（seq=1 已不是最新，不应覆盖 B 的结果）
    resolveA([makeMessage('msg-A', 'A 会话消息')])
    await flushMicrotasks()

    // messages 仍为 B 的结果，A 的结果被 loadSequenceNumber 防护丢弃
    expect(useSessionStore.getState().messages).toHaveLength(1)
    expect(useSessionStore.getState().messages[0].id).toBe('msg-B')
  })

  it('IndexedDB 加载返回非空消息且为最新请求时正常写入 state', async () => {
    useSessionStore.setState({
      messages: [makeMessage('old', '旧消息')],
      sessionId: 'old-session',
    })

    const newMessages = [makeMessage('new-1', '新消息1'), makeMessage('new-2', '新消息2')]
    persistenceMocks.loadMessages.mockResolvedValue(newMessages)

    useSessionStore.getState().setSessionId('new-session')

    // 切换瞬间 messages 仍为旧值
    expect(useSessionStore.getState().messages).toHaveLength(1)

    await flushMicrotasks()

    // 异步加载完成后 messages 被新数据覆盖
    expect(useSessionStore.getState().messages).toBe(newMessages)
    expect(useSessionStore.getState().messages).toHaveLength(2)
    expect(useSessionStore.getState().messages[0].id).toBe('new-1')
  })

  it('IndexedDB 读取失败时显式记录错误并暴露持久化不可用状态（不静默返回空）', async () => {
    // 无降级路径：读取失败必须可见 —— console.error + persistenceAvailable=false
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    persistenceMocks.loadMessages.mockRejectedValue(new Error('IndexedDB 打开失败'))
    persistenceMocks.isChatPersistenceAvailable.mockReturnValue(false)

    useSessionStore.getState().setSessionId('fail-session')

    await flushMicrotasks()

    expect(consoleErrorSpy).toHaveBeenCalled()
    expect(useSessionStore.getState().persistenceAvailable).toBe(false)
    // 失败时不得静默写入空消息覆盖已有内容
    expect(useSessionStore.getState().messages).toHaveLength(0)

    consoleErrorSpy.mockRestore()
  })
})
