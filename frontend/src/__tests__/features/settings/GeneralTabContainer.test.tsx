import '@testing-library/jest-dom/vitest'
import { waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { GeneralTabContainer } from '@/features/settings/containers/GeneralTabContainer'
import { useModelStore } from '@/features/chat/store/modelStore'
import { usePreferenceStore } from '@/features/chat/store/preferenceStore'
import { useSharedSettingsStore } from '@/features/settings/hooks/useSharedSettingsStore'
import { renderWithRouter } from '@/shared/routing/testing'

// 使用 vi.hoisted 提前建立 mock 引用，避免循环依赖
const preferenceSyncMocks = vi.hoisted(() => ({
  // 跟踪 loadServerPreferences 调用次数；返回空对象表示无字段须覆盖
  loadServerPreferences: vi.fn(() => Promise.resolve({} as Record<string, unknown>)),
}))

const apiMocks = vi.hoisted(() => ({
  // 跟踪 userAPI.getPreferences 调用次数（用于验证 GeneralTabContainer 不再直接调用）
  getPreferences: vi.fn(() => Promise.resolve({ data: { preferences: {} } })),
  updatePreferences: vi.fn(() => Promise.resolve({ data: { preferences: {} } })),
  promptsGetActive: vi.fn(() => Promise.resolve({ data: null })),
  promptsGetAll: vi.fn(() => Promise.resolve({ data: [] })),
}))

const modelApiMocks = vi.hoisted(() => ({
  getConfigurations: vi.fn(() => Promise.resolve({ data: { configurations: [] } })),
  getProviders: vi.fn(() => Promise.resolve({ data: { providers: [] } })),
  getCapabilities: vi.fn(() => Promise.resolve({ data: {} })),
  updateParameters: vi.fn(() => Promise.resolve({ data: { success: true } })),
  resetParameters: vi.fn(() => Promise.resolve({ data: { configuration: {} } })),
}))

const billingApiMocks = vi.hoisted(() => ({
  getModels: vi.fn(() => Promise.resolve({ data: { models: [] } })),
}))

// 关键 mock：替换 loadServerPreferences 以追踪 GeneralTabContainer 是否复用节流入口
vi.mock('@/shared/utils/preferenceSync', () => ({
  loadServerPreferences: preferenceSyncMocks.loadServerPreferences,
}))

vi.mock('@/shared/api/api', () => ({
  promptsAPI: {
    getAll: apiMocks.promptsGetAll,
    getActive: apiMocks.promptsGetActive,
    update: vi.fn(() => Promise.resolve({ data: {} })),
    create: vi.fn(() => Promise.resolve({ data: {} })),
  },
  userAPI: {
    getPreferences: apiMocks.getPreferences,
    updatePreferences: apiMocks.updatePreferences,
  },
}))

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: modelApiMocks,
}))

vi.mock('@/features/billing/billingApi', () => ({
  billingAPI: billingApiMocks,
}))

/** 创建测试用 QueryClient：关闭重试与 staleTime，确保每次 mount 都重新发起查询 */
function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 0,
        gcTime: 0,
      },
    },
  })
}

/** 包裹 QueryClientProvider 的渲染辅助函数 */
function renderWithQueryClient(element: React.ReactElement) {
  const testQueryClient = createTestQueryClient()
  return renderWithRouter(
    <QueryClientProvider client={testQueryClient}>
      {element}
    </QueryClientProvider>,
    {
      initialEntry: '/settings/general',
      routePath: '/settings/general',
    },
  )
}

describe('GeneralTabContainer - 复用 loadServerPreferences 节流', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    // 重置设置页共享 store，避免前一个用例填充的 lastLoadedAt 缓存导致后续用例跳过 getConfigurations
    useSharedSettingsStore.getState().reset()
    useModelStore.setState({
      selectedModel: '',
      modelOptions: [],
      modelLoading: false,
      modelError: null,
    })
    usePreferenceStore.setState({
      outputMode: 'stream',
    })
  })

  it('GeneralTabContainer 挂载时不重复调用 GET /user/preferences', async () => {
    // 直接渲染 GeneralTabContainer，触发首次挂载 effect
    renderWithQueryClient(<GeneralTabContainer />)

    // 等待 mount effect 触发 syncSettingsFromServer -> loadServerPreferences
    await waitFor(() => {
      expect(preferenceSyncMocks.loadServerPreferences).toHaveBeenCalledTimes(1)
    })

    // 关键断言：GeneralTabContainer 不再直接调用 userAPI.getPreferences，
    // 而是复用 loadServerPreferences 的 5 秒节流入口（与 App 启动期共用）
    expect(apiMocks.getPreferences).not.toHaveBeenCalled()

    // 等待微任务队列稳定，确保没有额外的延迟调用
    await new Promise((resolve) => setTimeout(resolve, 50))

    // 节流入口仅被调用 1 次（mount effect 触发一次 syncSettingsFromServer）
    expect(preferenceSyncMocks.loadServerPreferences).toHaveBeenCalledTimes(1)
    expect(apiMocks.getPreferences).not.toHaveBeenCalled()
  })

  it('loadServerPreferences 返回 null 时静默降级（保留本地值，不抛错）', async () => {
    // 模拟服务端不可用：loadServerPreferences 返回 null
    preferenceSyncMocks.loadServerPreferences.mockResolvedValueOnce(null)

    renderWithQueryClient(<GeneralTabContainer />)

    await waitFor(() => {
      expect(preferenceSyncMocks.loadServerPreferences).toHaveBeenCalledTimes(1)
    })

    // null 返回值不应导致组件抛错或调用 userAPI.getPreferences
    expect(apiMocks.getPreferences).not.toHaveBeenCalled()
  })

  it('loadServerPreferences 返回偏好对象时覆盖本地设置', async () => {
    // 模拟服务端返回主题为 dark、语言为 en
    preferenceSyncMocks.loadServerPreferences.mockResolvedValueOnce({
      theme: 'dark',
      language: 'en',
      maxToolCallRounds: 25,
    })

    renderWithQueryClient(<GeneralTabContainer />)

    await waitFor(() => {
      expect(preferenceSyncMocks.loadServerPreferences).toHaveBeenCalledTimes(1)
    })

    // 等待 setSettings 写入 localStorage
    await waitFor(() => {
      const raw = window.localStorage.getItem('app_settings')
      expect(raw).toBeTruthy()
      const saved = JSON.parse(raw || '{}')
      expect(saved.theme).toBe('dark')
      expect(saved.language).toBe('en')
      expect(saved.maxToolCallRounds).toBe(25)
    })
  })
})

describe('GeneralTabContainer - React Query 缓存复用', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    useSharedSettingsStore.getState().reset()
    useModelStore.setState({
      selectedModel: '',
      modelOptions: [],
      modelLoading: false,
      modelError: null,
    })
    usePreferenceStore.setState({
      outputMode: 'stream',
    })
  })

  it('挂载时通过 useQuery 调用 billingAPI.getModels 与 promptsAPI.getActive', async () => {
    renderWithQueryClient(<GeneralTabContainer />)

    // 等待 useQuery 触发 API 调用
    await waitFor(() => {
      expect(billingApiMocks.getModels).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(apiMocks.promptsGetActive).toHaveBeenCalledTimes(1)
    })
  })
})
