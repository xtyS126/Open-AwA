import { beforeEach, describe, expect, it, vi } from 'vitest'

// 使用 vi.hoisted 提前建立 mock 引用，避免循环依赖
const modelApiMocks = vi.hoisted(() => ({
  getConfigurations: vi.fn(),
  getProviders: vi.fn(),
  getModelsByProvider: vi.fn(),
}))

const modelStoreMocks = vi.hoisted(() => ({
  setModelLoading: vi.fn(),
  setModelError: vi.fn(),
  setModelOptions: vi.fn(),
  setSelectedModel: vi.fn(),
  selectedModel: '',
}))

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: modelApiMocks,
}))

vi.mock('@/features/chat/store/modelStore', () => ({
  useModelStore: {
    getState: () => ({
      selectedModel: modelStoreMocks.selectedModel,
      setModelLoading: modelStoreMocks.setModelLoading,
      setModelError: modelStoreMocks.setModelError,
      setModelOptions: modelStoreMocks.setModelOptions,
      setSelectedModel: modelStoreMocks.setSelectedModel,
    }),
  },
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
}))

import { preloadModelOptions } from '@/features/chat/utils/preloadModelOptions'

describe('preloadModelOptions - 模块级 Promise 去重锁', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 默认 mock：空配置 + 空供应商，确保 doPreload 走最简路径不触发额外分支
    modelApiMocks.getConfigurations.mockResolvedValue({ data: { configurations: [] } })
    modelApiMocks.getProviders.mockResolvedValue({ data: { providers: [] } })
    modelApiMocks.getModelsByProvider.mockResolvedValue({
      data: { source: 'remote', models: [] },
    })
    modelStoreMocks.selectedModel = ''
  })

  it('preloadModelOptions 并发调用复用 Promise', async () => {
    // 让 getConfigurations 延迟返回，确保 3 次调用都在 Promise 在途期间发起
    modelApiMocks.getConfigurations.mockImplementation(
      () =>
        new Promise((resolve) =>
          setTimeout(() => resolve({ data: { configurations: [] } }), 50)
        )
    )

    const results = await Promise.all([
      preloadModelOptions(),
      preloadModelOptions(),
      preloadModelOptions(),
    ])

    // 所有 3 个 Promise 都应 resolve
    expect(results).toHaveLength(3)
    // 去重锁生效：getConfigurations 只被调用 1 次（而非 3 次）
    expect(modelApiMocks.getConfigurations).toHaveBeenCalledTimes(1)
    // getProviders 同样只被调用 1 次（与 getConfigurations 在同一 Promise.all 中）
    expect(modelApiMocks.getProviders).toHaveBeenCalledTimes(1)
  })

  it('preloadModelOptions 失败后锁释放', async () => {
    // 第一次调用：getConfigurations reject
    // 注意：doPreload 内部 catch 会吞掉错误并设置 modelStore.modelError，不向上抛出
    // 因此 preloadModelOptions 仍 resolve，不会 reject（保持登录流程不阻塞）
    modelApiMocks.getConfigurations.mockRejectedValueOnce(new Error('network error'))

    // 第一次调用：应 resolve（doPreload 内部已 catch），错误通过 modelStore.setModelError 暴露
    await preloadModelOptions()

    // 验证错误路径确实被触发：setModelError 被调用了错误信息
    expect(modelStoreMocks.setModelError).toHaveBeenCalledWith('模型列表预加载失败，请稍后重试')
    // getConfigurations 被调用 1 次（第一次失败）
    expect(modelApiMocks.getConfigurations).toHaveBeenCalledTimes(1)

    // 第二次调用：mockRejectedValueOnce 已消费，getConfigurations 恢复为默认 resolve 行为
    await preloadModelOptions()

    // 锁已释放：第二次调用重新发起拉取，getConfigurations 共调用 2 次
    expect(modelApiMocks.getConfigurations).toHaveBeenCalledTimes(2)
  })
})
