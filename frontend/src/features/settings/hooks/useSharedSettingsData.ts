/**
 * 设置页面共享数据 Hook
 *
 * 早期版本使用 useState + useRef 实例级状态，导致每个 Tab Container 调用
 * useSharedSettingsData() 时得到独立的状态实例，引发重复 API 调用。
 *
 * 现已改为基于 Zustand 全局 store（useSharedSettingsStore），所有组件共享同一份
 * configurations / providers 状态，配合 stale-while-revalidate 与防重入锁
 * 避免重复请求。
 *
 * 本 Hook 保留原 API 形状以最小化对调用方的改动：
 * - 返回 configurations / providers / loadingConfigs / providerNameMap
 * - 返回 loadModelsData / invalidateTabCache / isTabLoaded / markTabLoaded
 * - loadedTabsRef 字段保留为兼容别名（指向 store 内部 Set 的只读代理）
 */
import { useMemo } from 'react'
import { useSharedSettingsStore } from './useSharedSettingsStore'
import type { ModelConfiguration, ModelProvider } from '@/features/settings/modelsApi'

/** 兼容旧 API 的 ref 对象形状 */
interface LoadedTabsRefLike {
  current: Set<string>
}

export function useSharedSettingsData() {
  const configurations = useSharedSettingsStore((s) => s.configurations)
  const providers = useSharedSettingsStore((s) => s.providers)
  const loadingConfigs = useSharedSettingsStore((s) => s.loadingConfigs)
  const loadedTabs = useSharedSettingsStore((s) => s.loadedTabs)
  const setConfigurations = useSharedSettingsStore((s) => s.setConfigurations)
  const setProviders = useSharedSettingsStore((s) => s.setProviders)
  const loadModelsData = useSharedSettingsStore((s) => s.loadModelsData)
  const invalidateTabCache = useSharedSettingsStore((s) => s.invalidateTabCache)
  const isTabLoaded = useSharedSettingsStore((s) => s.isTabLoaded)
  const markTabLoaded = useSharedSettingsStore((s) => s.markTabLoaded)

  // 供应商名称映射
  const providerNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    providers.forEach((p: ModelProvider) => {
      map[p.id] = p.display_name || p.name || p.id
    })
    return map
  }, [providers])

  // 兼容旧 API：loadedTabsRef.current 指向 store 内部的 Set
  // 注意：调用方不应通过 ref 直接修改 Set，应使用 markTabLoaded / invalidateTabCache
  const loadedTabsRef: LoadedTabsRefLike = useMemo(
    () => ({ current: loadedTabs }),
    [loadedTabs],
  )

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

// 类型导出，便于调用方声明
export type { ModelConfiguration, ModelProvider }
