/**
 * 模型配置容器 Hook
 * 管理模型配置相关的状态和逻辑，包括模型参数的编辑、保存、重置等功能。
 *
 * 将原本 ApiTabContainer 中与模型配置卡片相关的状态和操作
 * 提取为独立的自定义 Hook，实现关注点分离。
 *
 * 改造说明（fix-performance-remaining-issues 模块 C）：
 *   - 原实现使用手动 axios 调用 modelsAPI.getCapabilities，每次展开卡片都触发请求
 *   - 现改用 useQuery + queryClient.invalidateQueries，切换 configId 时复用缓存
 *   - queryKey: ['billing', 'configurations', configId, 'capabilities']
 *   - 展开卡片时通过 expandedConfigId 启用查询，折叠时禁用
 *   - 已加载过参数的模型不再被覆盖（保留用户编辑）
 */
import { useCallback, useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { modelsAPI } from '@/features/settings/modelsApi'
import type { ModelConfiguration, ModelCapabilitiesResponse } from '@/features/settings/modelsApi'
import { useNotification } from '@/shared/hooks/useNotification'
import { buildModelEditParams } from '@/features/settings/SettingsPage.utils'
import type { ModelEditParams } from '@/features/settings/components/ModelParameterEditor'

/** useModelConfig Hook 的入参接口 */
export interface UseModelConfigParams {
  /** 所有配置记录 */
  configurations: ModelConfiguration[]
  /** 当前供应商表单的 provider 字段 */
  providerFormProvider: string
  /** 加载模型配置数据的回调 */
  loadModelsData: () => Promise<void>
}

/** useModelConfig Hook 的返回值接口 */
export interface UseModelConfigReturn {
  // 模型配置状态
  expandedModelConfigs: Set<string>
  setExpandedModelConfigs: React.Dispatch<React.SetStateAction<Set<string>>>
  modelEditParams: Record<string, ModelEditParams>
  setModelEditParams: React.Dispatch<React.SetStateAction<Record<string, ModelEditParams>>>
  savingModelConfig: Record<string, boolean>

  // 回调函数
  toggleModelConfig: (modelName: string) => Promise<void>
  updateModelEditParam: (modelName: string, field: keyof ModelEditParams, value: number) => void
  handleSaveModelConfig: (modelName: string) => Promise<void>
  handleResetModelConfig: (modelName: string) => Promise<void>
}

/**
 * 模型配置管理 Hook
 *
 * 封装模型配置卡片相关的所有状态和操作逻辑，包括：
 * - 模型配置卡片的展开/折叠（手风琴模式，同时仅展开一个）
 * - 模型参数的编辑和保存
 * - 模型参数的重置
 * - 通过 useQuery 缓存 capabilities，切换模型时复用缓存
 */
export function useModelConfig({
  configurations,
  providerFormProvider,
  loadModelsData,
}: UseModelConfigParams): UseModelConfigReturn {
  const { showNotification } = useNotification(3000)
  const queryClient = useQueryClient()

  // 模型独立配置卡片状态
  const [expandedModelConfigs, setExpandedModelConfigs] = useState<Set<string>>(new Set())
  const [modelEditParams, setModelEditParams] = useState<Record<string, ModelEditParams>>({})
  const [savingModelConfig, setSavingModelConfig] = useState<Record<string, boolean>>({})

  // 从展开的 configKey 中推导当前展开的 modelName 与 configId
  // 手风琴模式：同时仅展开一个，取 Set 中第一个条目
  const expandedConfigKey = expandedModelConfigs.size > 0
    ? Array.from(expandedModelConfigs)[0]
    : null
  // configKey 格式为 `${providerFormProvider}:${modelName}`
  const expandedModelName = expandedConfigKey
    ? expandedConfigKey.split(':').slice(1).join(':')
    : null
  const expandedConfig = expandedModelName
    ? configurations.find(c => c.provider === providerFormProvider && c.model === expandedModelName)
    : undefined
  const expandedConfigId = expandedConfig?.id ?? null

  // 模型能力查询：按 configId 缓存，configId 为空时禁用查询
  // 切换 configId 时才发起新请求，切回复用缓存（staleTime 60s 内不重复请求）
  const { data: capabilitiesData } = useQuery<ModelCapabilitiesResponse>({
    queryKey: ['billing', 'configurations', expandedConfigId, 'capabilities'],
    queryFn: () => modelsAPI.getCapabilities(expandedConfigId as number).then(r => r.data),
    enabled: !!expandedConfigId,
  })

  // 能力数据加载完成后同步 modelEditParams（仅在该模型尚未加载参数时设置，避免覆盖用户编辑）
  useEffect(() => {
    if (!capabilitiesData || !expandedModelName || !expandedConfig) {
      return
    }
    // 已加载过参数的模型不再覆盖（保留用户编辑与重置后的值）
    if (modelEditParams[expandedModelName]) {
      return
    }
    setModelEditParams(prev => ({
      ...prev,
      [expandedModelName]: buildModelEditParams(expandedConfig, capabilitiesData),
    }))
  }, [capabilitiesData, expandedModelName, expandedConfig, modelEditParams])

  /** 切换模型配置卡片展开/折叠 */
  const toggleModelConfig = useCallback(async (modelName: string) => {
    const configKey = `${providerFormProvider}:${modelName}`

    setExpandedModelConfigs(prev => {
      const next = new Set<string>()
      if (!prev.has(configKey)) {
        // 展开当前，折叠其他（手风琴模式）
        next.add(configKey)
      }
      return next
    })

    // capabilities 由 useQuery 自动拉取（enabled 由 expandedConfigId 控制）
    // 此处无需手动调用 getCapabilities，React Query 会复用缓存
  }, [providerFormProvider])

  /** 更新模型编辑参数 */
  const updateModelEditParam = useCallback((modelName: string, field: keyof ModelEditParams, value: number) => {
    setModelEditParams(prev => ({
      ...prev,
      [modelName]: { ...prev[modelName], [field]: value },
    }))
  }, [])

  /** 保存单个模型配置 */
  const handleSaveModelConfig = useCallback(async (modelName: string) => {
    const params = modelEditParams[modelName]
    if (!params) return

    const config = configurations.find(
      c => c.provider === providerFormProvider && c.model === modelName
    )
    if (!config) return

    setSavingModelConfig(prev => ({ ...prev, [modelName]: true }))
    try {
      await modelsAPI.updateParameters(config.id, {
        temperature: params.temperature,
        top_p: params.top_p,
        // max_tokens 为 0 表示"使用模型默认上限"，传 null 让后端使用默认值
        max_tokens_limit: params.max_tokens > 0 ? params.max_tokens : null,
        frequency_penalty: params.frequency_penalty,
        presence_penalty: params.presence_penalty,
        timeout: params.timeout > 0 ? params.timeout : null,
        retry_count: params.retry_count,
      })
      showNotification({ type: 'success', text: `模型「${modelName}」参数保存成功` })
      // 刷新配置列表以获取最新值，并失效 capabilities 缓存（保存后端可能更新默认值）
      await loadModelsData()
      await queryClient.invalidateQueries({
        queryKey: ['billing', 'configurations', config.id, 'capabilities'],
      })
    } catch {
      showNotification({ type: 'error', text: `模型「${modelName}」参数保存失败` })
    } finally {
      setSavingModelConfig(prev => ({ ...prev, [modelName]: false }))
    }
  }, [modelEditParams, configurations, providerFormProvider, showNotification, loadModelsData, queryClient])

  /** 重置单个模型配置为默认值 */
  const handleResetModelConfig = useCallback(async (modelName: string) => {
    const config = configurations.find(
      c => c.provider === providerFormProvider && c.model === modelName
    )
    if (!config) return

    setSavingModelConfig(prev => ({ ...prev, [modelName]: true }))
    try {
      const res = await modelsAPI.resetParameters(config.id)
      const updatedConfig = res.data.configuration
      // 回填默认值（reset 后 capabilities 返回的已是默认值，无需再次请求）
      setModelEditParams(prev => ({
        ...prev,
        [modelName]: buildModelEditParams(updatedConfig),
      }))
      showNotification({ type: 'success', text: `模型「${modelName}」已重置为默认参数` })
      await loadModelsData()
      // 失效 capabilities 缓存，确保下次展开时拉取最新默认值
      await queryClient.invalidateQueries({
        queryKey: ['billing', 'configurations', config.id, 'capabilities'],
      })
    } catch {
      showNotification({ type: 'error', text: `模型「${modelName}」重置失败` })
    } finally {
      setSavingModelConfig(prev => ({ ...prev, [modelName]: false }))
    }
  }, [configurations, providerFormProvider, showNotification, loadModelsData, queryClient])

  return {
    // 模型配置状态
    expandedModelConfigs,
    setExpandedModelConfigs,
    modelEditParams,
    setModelEditParams,
    savingModelConfig,

    // 回调函数
    toggleModelConfig,
    updateModelEditParam,
    handleSaveModelConfig,
    handleResetModelConfig,
  }
}
