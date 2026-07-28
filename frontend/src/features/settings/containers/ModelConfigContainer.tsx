/**
 * 模型配置容器 Hook
 * 管理模型配置相关的状态和逻辑，包括模型参数的编辑、保存、重置等功能。
 *
 * 将原本 ApiTabContainer 中与模型配置卡片相关的状态和操作
 * 提取为独立的自定义 Hook，实现关注点分离。
 */
import { useCallback, useRef, useState } from 'react'
import { modelsAPI } from '@/features/settings/modelsApi'
import type { ModelConfiguration } from '@/features/settings/modelsApi'
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
 * - 模型配置卡片的展开/折叠
 * - 模型参数的编辑和保存
 * - 模型参数的重置
 */
export function useModelConfig({
  configurations,
  providerFormProvider,
  loadModelsData,
}: UseModelConfigParams): UseModelConfigReturn {
  const { showNotification } = useNotification(3000)

  // 模型独立配置卡片状态
  const [expandedModelConfigs, setExpandedModelConfigs] = useState<Set<string>>(new Set())
  const [modelEditParams, setModelEditParams] = useState<Record<string, ModelEditParams>>({})
  const [savingModelConfig, setSavingModelConfig] = useState<Record<string, boolean>>({})
  const loadingCapsRef = useRef<Set<string>>(new Set())

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

    // 如果正在展开且尚未加载该模型参数，则从 API 获取
    // 使用 ref 防止快速双击触发重复请求
    if (!modelEditParams[modelName] && !loadingCapsRef.current.has(modelName)) {
      loadingCapsRef.current.add(modelName)
      const config = configurations.find(
        c => c.provider === providerFormProvider && c.model === modelName
      )
      if (!config) {
        loadingCapsRef.current.delete(modelName)
        return
      }

      let caps: unknown | undefined
      try {
        const capRes = await modelsAPI.getCapabilities(config.id)
        caps = capRes.data
      } catch {
        // 降级：直接使用配置中的值
      } finally {
        loadingCapsRef.current.delete(modelName)
      }

      setModelEditParams(prev => ({
        ...prev,
        [modelName]: buildModelEditParams(config, caps as { defaults: { temperature: number; top_k: number; max_tokens: number; frequency_penalty: number; presence_penalty: number; timeout: number; retry_count: number } } | undefined),
      }))
    }
  }, [providerFormProvider, modelEditParams, configurations])

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
      // 刷新配置列表以获取最新值
      await loadModelsData()
    } catch {
      showNotification({ type: 'error', text: `模型「${modelName}」参数保存失败` })
    } finally {
      setSavingModelConfig(prev => ({ ...prev, [modelName]: false }))
    }
  }, [modelEditParams, configurations, providerFormProvider, showNotification, loadModelsData])

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
    } catch {
      showNotification({ type: 'error', text: `模型「${modelName}」重置失败` })
    } finally {
      setSavingModelConfig(prev => ({ ...prev, [modelName]: false }))
    }
  }, [configurations, providerFormProvider, showNotification, loadModelsData])

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
