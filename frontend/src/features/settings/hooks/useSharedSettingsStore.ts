/**
 * 设置页面共享数据全局 Store
 *
 * 使用 Zustand 创建模块级单例 store，确保所有调用 useSharedSettingsData() 的组件
 * 共享同一份 configurations / providers 状态，避免每个 Tab Container 重复拉取。
 *
 * 改造说明（fix-performance-remaining-issues-v2 模块 C3）：
 *   - 原实现使用 lastLoadedAt + STALE_THRESHOLD_MS 自实现 SWR 5 分钟缓存
 *   - 现改用 React Query 的 queryClient.fetchQuery，由 staleTime=60s 接管缓存策略
 *   - 删除 loadingPromise 防重入锁（React Query 内置请求去重）
 *   - 删除 lastLoadedAt 与 STALE_THRESHOLD_MS（React Query staleTime 接管）
 *   - 保留 Zustand store 结构与 set/get 调用，外部 API 形状不变
 *
 * 设计要点：
 * - configurations / providers / loadingConfigs 为全局状态，所有组件共享
 * - loadedTabs 为 Set<string> 状态字段，记录已加载的 Tab
 * - loadModelsData 通过 queryClient.fetchQuery 复用 React Query 缓存
 */
import { create } from 'zustand'
import { modelsAPI, ModelConfiguration, ModelProvider } from '@/features/settings/modelsApi'
import { queryClient } from '@/shared/api/queryClient'
import { appLogger } from '@/shared/utils/logger'

interface SharedSettingsState {
  configurations: ModelConfiguration[]
  providers: ModelProvider[]
  loadingConfigs: boolean
  loadedTabs: Set<string>
  setConfigurations: (configs: ModelConfiguration[]) => void
  setProviders: (providers: ModelProvider[]) => void
  setLoadingConfigs: (loading: boolean) => void
  /** 加载模型配置和供应商列表（通过 React Query 缓存复用） */
  loadModelsData: (force?: boolean) => Promise<void>
  /** 标记 Tab 缓存已失效 */
  invalidateTabCache: (tabs: string[]) => void
  /** 检查 Tab 是否已加载 */
  isTabLoaded: (tab: string) => boolean
  /** 标记 Tab 为已加载 */
  markTabLoaded: (tab: string) => void
  /** 重置整个 store（用于退出登录等场景） */
  reset: () => void
}

export const useSharedSettingsStore = create<SharedSettingsState>((set, get) => ({
  configurations: [],
  providers: [],
  loadingConfigs: false,
  loadedTabs: new Set<string>(),

  setConfigurations: (configs) => set({ configurations: configs }),
  setProviders: (providers) => set({ providers }),
  setLoadingConfigs: (loading) => set({ loadingConfigs: loading }),

  loadModelsData: async (force = false) => {
    // force=true 时失效缓存，强制下次 fetchQuery 重新拉取
    if (force) {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['billing', 'configurations'] }),
        queryClient.invalidateQueries({ queryKey: ['billing', 'providers'] }),
      ])
    }

    set({ loadingConfigs: true })
    try {
      // 通过 queryClient.fetchQuery 复用 React Query 缓存：
      // - staleTime=60s 内复用缓存，避免多 Tab 切换重复请求
      // - 并发调用自动去重（React Query 内置请求去重，替代原 loadingPromise 锁）
      const [configsRes, providersRes] = await Promise.all([
        queryClient.fetchQuery({
          queryKey: ['billing', 'configurations'],
          queryFn: () => modelsAPI.getConfigurations(),
        }),
        queryClient.fetchQuery({
          queryKey: ['billing', 'providers'],
          queryFn: () => modelsAPI.getProviders(),
        }),
      ])
      const configs: ModelConfiguration[] = configsRes.data.configurations || []
      const providers: ModelProvider[] = providersRes.data.providers || []
      set({ configurations: configs, providers })
    } catch {
      appLogger.error({
        event: 'models_data_load_failed',
        message: 'Failed to load models data',
        module: 'settings',
      })
    } finally {
      set({ loadingConfigs: false })
    }
  },

  invalidateTabCache: (tabs) => {
    const current = get().loadedTabs
    const next = new Set(current)
    tabs.forEach((t) => next.delete(t))
    set({ loadedTabs: next })
  },

  isTabLoaded: (tab) => get().loadedTabs.has(tab),

  markTabLoaded: (tab) => {
    const current = get().loadedTabs
    if (current.has(tab)) return
    const next = new Set(current)
    next.add(tab)
    set({ loadedTabs: next })
  },

  reset: () =>
    set({
      configurations: [],
      providers: [],
      loadingConfigs: false,
      loadedTabs: new Set<string>(),
    }),
}))