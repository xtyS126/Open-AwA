/**
 * 设置页面共享数据全局 Store
 *
 * 使用 Zustand 创建模块级单例 store，确保所有调用 useSharedSettingsData() 的组件
 * 共享同一份 configurations / providers 状态，避免每个 Tab Container 重复拉取。
 *
 * 设计要点：
 * - configurations / providers / loadingConfigs 为全局状态，所有组件共享
 * - loadedTabsRef 改为 Set<string> 状态字段，记录已加载的 Tab
 * - loadModelsData 内置防重入锁（loadingRef），并发调用时复用同一 Promise
 */
import { create } from 'zustand'
import { modelsAPI, ModelConfiguration, ModelProvider } from '@/features/settings/modelsApi'
import { appLogger } from '@/shared/utils/logger'

interface SharedSettingsState {
  configurations: ModelConfiguration[]
  providers: ModelProvider[]
  loadingConfigs: boolean
  loadedTabs: Set<string>
  /** 防重入锁：正在进行中的加载 Promise */
  loadingPromise: Promise<void> | null
  /** 数据加载时间戳，用于 stale-while-revalidate 策略 */
  lastLoadedAt: number
  setConfigurations: (configs: ModelConfiguration[]) => void
  setProviders: (providers: ModelProvider[]) => void
  setLoadingConfigs: (loading: boolean) => void
  /** 加载模型配置和供应商列表（并行请求，防重入） */
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

/** 数据过期阈值：5 分钟内不重复拉取 */
const STALE_THRESHOLD_MS = 5 * 60 * 1000

export const useSharedSettingsStore = create<SharedSettingsState>((set, get) => ({
  configurations: [],
  providers: [],
  loadingConfigs: false,
  loadedTabs: new Set<string>(),
  loadingPromise: null,
  lastLoadedAt: 0,

  setConfigurations: (configs) => set({ configurations: configs }),
  setProviders: (providers) => set({ providers }),
  setLoadingConfigs: (loading) => set({ loadingConfigs: loading }),

  loadModelsData: async (force = false) => {
    const state = get()
    // 防重入：如果正在加载，复用现有 Promise
    if (state.loadingPromise) {
      return state.loadingPromise
    }
    // stale-while-revalidate：5 分钟内不强制刷新
    const now = Date.now()
    if (!force && state.lastLoadedAt && now - state.lastLoadedAt < STALE_THRESHOLD_MS) {
      return
    }

    const promise = (async () => {
      set({ loadingConfigs: true })
      try {
        const [configsRes, providersRes] = await Promise.all([
          modelsAPI.getConfigurations(),
          modelsAPI.getProviders(),
        ])
        const configs: ModelConfiguration[] = configsRes.data.configurations || []
        const providers: ModelProvider[] = providersRes.data.providers || []
        set({
          configurations: configs,
          providers,
          lastLoadedAt: Date.now(),
        })
      } catch {
        appLogger.error({
          event: 'models_data_load_failed',
          message: 'Failed to load models data',
          module: 'settings',
        })
      } finally {
        set({ loadingConfigs: false, loadingPromise: null })
      }
    })()

    set({ loadingPromise: promise })
    return promise
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
      loadingPromise: null,
      lastLoadedAt: 0,
    }),
}))
