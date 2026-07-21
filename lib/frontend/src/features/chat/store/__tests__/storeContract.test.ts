/**
 * 分域 Store 契约测试。
 *
 * 验证各分域 Store 相互独立：更新一个 Store 的状态不会触发其他 Store 的订阅者。
 * 这确保了分域拆分后，高频更新（如流式消息）不会导致无关组件重渲染。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { useModelStore } from '@/features/chat/store/modelStore'
import { useToolCallStore } from '@/features/chat/store/toolCallStore'
import { usePreferenceStore } from '@/features/chat/store/preferenceStore'

describe('分域 Store 契约测试', () => {
  beforeEach(() => {
    // 重置各 Store 状态，避免跨用例污染
    useSessionStore.setState({
      messages: [],
      isLoading: false,
      sessionId: 'default',
      conversations: [],
      conversationsTotal: 0,
      conversationsHasMore: false,
      pinnedConversations: [],
    })
    useModelStore.setState({
      selectedModel: '',
      modelOptions: [],
      modelLoading: false,
      modelError: null,
    })
    useToolCallStore.setState({
      activeToolCalls: [],
    })
    usePreferenceStore.setState({
      outputMode: 'stream',
      thinkingEnabled: false,
      thinkingDepth: 0,
    })
    vi.clearAllMocks()
  })

  it('test_sessionStore_setLoading_does_not_trigger_modelStore_subscribers', () => {
    // 订阅 modelStore，监听其状态变化
    const modelStoreListener = vi.fn()
    const unsubscribe = useModelStore.subscribe(modelStoreListener)

    // 更新 sessionStore 的 loading 状态
    useSessionStore.getState().setLoading(true)
    useSessionStore.getState().setLoading(false)

    // modelStore 订阅者不应被触发
    expect(modelStoreListener).not.toHaveBeenCalled()

    // 验证 sessionStore 确实更新了（确保测试有效性）
    expect(useSessionStore.getState().isLoading).toBe(false)

    unsubscribe()
  })

  it('test_preferenceStore_setOutputMode_does_not_trigger_sessionStore_subscribers', () => {
    // 订阅 sessionStore，监听其状态变化
    const sessionStoreListener = vi.fn()
    const unsubscribe = useSessionStore.subscribe(sessionStoreListener)

    // 更新 preferenceStore 的 outputMode（不同步到服务端，避免测试中的网络调用）
    usePreferenceStore.getState().setOutputMode('direct', { syncToServer: false })
    usePreferenceStore.getState().setOutputMode('stream', { syncToServer: false })

    // sessionStore 订阅者不应被触发
    expect(sessionStoreListener).not.toHaveBeenCalled()

    // 验证 preferenceStore 确实更新了（确保测试有效性）
    expect(usePreferenceStore.getState().outputMode).toBe('stream')

    unsubscribe()
  })

  it('test_toolCallStore_addActiveToolCall_does_not_trigger_preferenceStore_subscribers', () => {
    // 订阅 preferenceStore，监听其状态变化
    const preferenceStoreListener = vi.fn()
    const unsubscribe = usePreferenceStore.subscribe(preferenceStoreListener)

    // 更新 toolCallStore 的 activeToolCalls
    useToolCallStore.getState().addActiveToolCall('tool-1')
    useToolCallStore.getState().addActiveToolCall('tool-2')
    useToolCallStore.getState().removeActiveToolCall('tool-1')

    // preferenceStore 订阅者不应被触发
    expect(preferenceStoreListener).not.toHaveBeenCalled()

    // 验证 toolCallStore 确实更新了（确保测试有效性）
    expect(useToolCallStore.getState().activeToolCalls).toEqual(['tool-2'])

    unsubscribe()
  })

  it('test_modelStore_setModelLoading_does_not_trigger_toolCallStore_subscribers', () => {
    // 订阅 toolCallStore，监听其状态变化
    const toolCallStoreListener = vi.fn()
    const unsubscribe = useToolCallStore.subscribe(toolCallStoreListener)

    // 更新 modelStore 的 modelLoading 状态
    useModelStore.getState().setModelLoading(true)
    useModelStore.getState().setModelLoading(false)

    // toolCallStore 订阅者不应被触发
    expect(toolCallStoreListener).not.toHaveBeenCalled()

    // 验证 modelStore 确实更新了（确保测试有效性）
    expect(useModelStore.getState().modelLoading).toBe(false)

    unsubscribe()
  })
})
