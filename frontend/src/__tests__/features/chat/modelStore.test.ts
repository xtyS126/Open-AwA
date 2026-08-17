import { beforeEach, describe, expect, it, vi } from 'vitest'

// 使用 vi.hoisted 提前建立 mock 引用，确保在 vi.mock 工厂中可访问
const safeStorageMocks = vi.hoisted(() => ({
  safeGetItem: vi.fn((_key: string, defaultValue: string = '') => defaultValue),
  safeSetItem: vi.fn(),
}))

const chatStoreEffectsMocks = vi.hoisted(() => ({
  persistSelectedModel: vi.fn(),
}))

const preferenceStoreMocks = vi.hoisted(() => ({
  setThinkingEnabled: vi.fn(),
}))

// 屏蔽 safeStorage，避免测试触碰真实 localStorage
// 注意：modelStore 现经 registerLogoutHandler 传递依赖 authStore -> client，
// client 模块级代码会调用 safeSessionGetItem，mock 必须补齐全部导出
vi.mock('@/shared/utils/safeStorage', () => ({
  safeGetItem: safeStorageMocks.safeGetItem,
  safeSetItem: safeStorageMocks.safeSetItem,
  safeSessionGetItem: vi.fn((_key: string, defaultValue: string = '') => defaultValue),
  safeSessionSetItem: vi.fn(),
}))

// 屏蔽 chatStoreEffects，避免触发 localStorage 写入与服务端同步
vi.mock('@/features/chat/store/chatStoreEffects', () => ({
  persistSelectedModel: chatStoreEffectsMocks.persistSelectedModel,
}))

// 屏蔽 preferenceStore，避免跨域副作用真实执行
vi.mock('@/features/chat/store/preferenceStore', () => ({
  usePreferenceStore: {
    getState: () => ({
      setThinkingEnabled: preferenceStoreMocks.setThinkingEnabled,
    }),
  },
}))

import { useModelStore } from '@/features/chat/store/modelStore'

describe('useModelStore - setSelectedModel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 默认 safeGetItem 返回 defaultValue（覆盖 chat_selected_model 与 chat_thinking_enabled）
    safeStorageMocks.safeGetItem.mockImplementation((_key: string, defaultValue: string = '') => defaultValue)
    // 重置 store 状态，避免跨用例污染
    useModelStore.setState({
      selectedModel: '',
      modelOptions: [],
      modelLoading: false,
      modelError: null,
    })
  })

  it('setSelectedModel 相同 model 跳过副作用', () => {
    // 准备：store 已选中某模型
    useModelStore.setState({ selectedModel: 'deepseek:deepseek-v4-pro' })

    // 调用 setSelectedModel 传入相同值
    useModelStore.getState().setSelectedModel('deepseek:deepseek-v4-pro')

    // 验证：未触发持久化副作用（既不写 localStorage 也不发 PUT /api/user/preferences）
    expect(chatStoreEffectsMocks.persistSelectedModel).not.toHaveBeenCalled()
    // 验证：未触发思考模式开关（短路在推理模型检查之前返回，即使传入的是推理模型也不会触发）
    expect(preferenceStoreMocks.setThinkingEnabled).not.toHaveBeenCalled()
    // 验证：selectedModel 保持不变
    expect(useModelStore.getState().selectedModel).toBe('deepseek:deepseek-v4-pro')
  })

  it('setSelectedModel 不同 model 正常路径', () => {
    // 准备：store 已选中旧模型
    useModelStore.setState({ selectedModel: 'deepseek:deepseek-v4-pro' })

    // 调用 setSelectedModel 切换到新模型，显式同步到服务端
    useModelStore.getState().setSelectedModel('openai:gpt-4', { syncToServer: true })

    // 验证：触发持久化副作用，参数为 (新模型, true)
    expect(chatStoreEffectsMocks.persistSelectedModel).toHaveBeenCalledWith('openai:gpt-4', true)
    // 验证：selectedModel 已更新
    expect(useModelStore.getState().selectedModel).toBe('openai:gpt-4')
  })

  it('setSelectedModel 推理模型自动开启思考模式', () => {
    // 准备：store 当前无选中模型
    useModelStore.setState({ selectedModel: '' })
    // 模拟用户未显式关闭思考模式（chat_thinking_enabled 既非 'false' 也未设置）
    safeStorageMocks.safeGetItem.mockImplementation((key: string, defaultValue: string = '') => {
      if (key === 'chat_thinking_enabled') return ''
      return defaultValue
    })

    // 调用 setSelectedModel 传入推理模型
    useModelStore.getState().setSelectedModel('deepseek:deepseek-reasoner')

    // 验证：跨域调用 preferenceStore 开启思考模式，且不同步到服务端（由 thinkingEnabled 自身同步）
    expect(preferenceStoreMocks.setThinkingEnabled).toHaveBeenCalledWith(true, { syncToServer: false })
  })
})

describe('useModelStore - setModelOptions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 默认 safeGetItem 返回 defaultValue（覆盖 chat_selected_model 与 chat_thinking_enabled）
    safeStorageMocks.safeGetItem.mockImplementation((_key: string, defaultValue: string = '') => defaultValue)
    // 重置 store 状态，避免跨用例污染
    useModelStore.setState({
      selectedModel: '',
      modelOptions: [],
      modelLoading: false,
      modelError: null,
    })
  })

  it('setModelOptions 失效清空时调用 persistSelectedModel("", true)', () => {
    // 准备：store 已选中失效模型 deepseek:old-model
    useModelStore.setState({ selectedModel: 'deepseek:old-model' })

    // 调用 setModelOptions 传入不包含当前模型的新选项列表
    useModelStore.getState().setModelOptions([
      { id: 'openai:gpt-4', provider: 'openai', model: 'gpt-4', display_name: 'OpenAI GPT-4' },
    ])

    // 验证：触发空值同步到服务端，参数为 ('', true)
    expect(chatStoreEffectsMocks.persistSelectedModel).toHaveBeenCalledWith('', true)
    // 验证：清空 localStorage 中的 chat_selected_model
    expect(safeStorageMocks.safeSetItem).toHaveBeenCalledWith('chat_selected_model', '')
    // 验证：selectedModel 已被清空
    expect(useModelStore.getState().selectedModel).toBe('')
    // 验证：modelOptions 已更新为新选项列表
    expect(useModelStore.getState().modelOptions).toHaveLength(1)
    expect(useModelStore.getState().modelOptions[0].id).toBe('openai:gpt-4')
  })

  it('setModelOptions options 为空时不清空', () => {
    // 准备：store 已选中有效模型
    useModelStore.setState({ selectedModel: 'deepseek:deepseek-v4-pro' })

    // 调用 setModelOptions 传入空数组（模拟加载失败或无可用模型）
    useModelStore.getState().setModelOptions([])

    // 验证：未触发服务端同步
    expect(chatStoreEffectsMocks.persistSelectedModel).not.toHaveBeenCalled()
    // 验证：未清空 localStorage 中的 chat_selected_model
    expect(safeStorageMocks.safeSetItem).not.toHaveBeenCalledWith('chat_selected_model', '')
    // 验证：selectedModel 保持不变
    expect(useModelStore.getState().selectedModel).toBe('deepseek:deepseek-v4-pro')
    // 验证：modelOptions 已更新为空数组
    expect(useModelStore.getState().modelOptions).toEqual([])
  })

  it('setModelOptions 当前模型仍有效时保留', () => {
    // 准备：store 已选中有效模型
    useModelStore.setState({ selectedModel: 'deepseek:deepseek-v4-pro' })

    // 调用 setModelOptions 传入包含当前模型的新选项列表
    useModelStore.getState().setModelOptions([
      { id: 'deepseek:deepseek-v4-pro', provider: 'deepseek', model: 'deepseek-v4-pro', display_name: 'DeepSeek V4 Pro' },
      { id: 'openai:gpt-4', provider: 'openai', model: 'gpt-4', display_name: 'OpenAI GPT-4' },
    ])

    // 验证：未触发服务端同步（模型仍有效，无需清空）
    expect(chatStoreEffectsMocks.persistSelectedModel).not.toHaveBeenCalled()
    // 验证：selectedModel 保持不变
    expect(useModelStore.getState().selectedModel).toBe('deepseek:deepseek-v4-pro')
    // 验证：modelOptions 已更新为含 2 个选项的列表
    expect(useModelStore.getState().modelOptions).toHaveLength(2)
  })
})
