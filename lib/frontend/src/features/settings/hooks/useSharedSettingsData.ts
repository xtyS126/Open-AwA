/**
 * 设置页面共享数据 Hook
 * 管理跨 Tab 共享的配置数据（configurations、providers），避免重复 API 调用
 */
import { useState, useCallback, useRef, useMemo } from 'react'
import { modelsAPI, ModelConfiguration, ModelProvider } from '@/features/settings/modelsApi'
import { appLogger } from '@/shared/utils/logger'

export function useSharedSettingsData() {
  const [configurations, setConfigurations] = useState<ModelConfiguration[]>([])
  const [providers, setProviders] = useState<ModelProvider[]>([])
  const [loadingConfigs, setLoadingConfigs] = useState(false)

  // 记录已加载的 Tab，避免重复请求
  const loadedTabsRef = useRef<Set<string>>(new Set())

  /** 加载模型配置和供应商列表（并行请求） */
  const loadModelsData = useCallback(async () => {
    setLoadingConfigs(true)
    try {
      const [configsRes, providersRes] = await Promise.all([
        modelsAPI.getConfigurations(),
        modelsAPI.getProviders()
      ])
      const configs: ModelConfiguration[] = configsRes.data.configurations || []
      setConfigurations(configs)
      setProviders(providersRes.data.providers || [])
    } catch {
      appLogger.error({ event: 'models_data_load_failed', message: 'Failed to load models data', module: 'settings' })
    } finally {
      setLoadingConfigs(false)
    }
  }, [])

  /** 标记 Tab 缓存已失效（用于数据变更后刷新） */
  const invalidateTabCache = useCallback((tabs: string[]) => {
    tabs.forEach(t => loadedTabsRef.current.delete(t))
  }, [])

  /** 检查 Tab 是否已加载 */
  const isTabLoaded = useCallback((tab: string) => {
    return loadedTabsRef.current.has(tab)
  }, [])

  /** 标记 Tab 为已加载 */
  const markTabLoaded = useCallback((tab: string) => {
    loadedTabsRef.current.add(tab)
  }, [])

  /** 供应商名称映射 */
  const providerNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    providers.forEach((p) => {
      map[p.id] = p.display_name || p.name || p.id
    })
    return map
  }, [providers])

  return {
    configurations,
    setConfigurations,
    providers,
    setProviders,
    loadingConfigs,
    providerNameMap,
    loadModelsData,
    invalidateTabCache,
    isTabLoaded,
    markTabLoaded,
    loadedTabsRef,
  }
}
