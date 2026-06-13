/**
 * 通用设置 Tab 容器组件
 * 管理通用设置相关的所有状态和数据获取逻辑
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { lazy, Suspense } from 'react'
import { promptsAPI, userAPI } from '@/shared/api/api'
import { billingAPI, ModelPricing } from '@/features/billing/billingApi'
import { modelsAPI, ModelCapabilitiesResponse, ModelProvider } from '@/features/settings/modelsApi'
import { useGlobalModelSelection } from '@/features/settings/hooks/useGlobalModelSelection'
import { useSharedSettingsData } from '@/features/settings/hooks/useSharedSettingsData'
import {
  REMOTE_MODEL_CACHE_TTL_MS,
  buildPersistedSettings,
  isPersistedSettings,
} from '@/features/settings/SettingsPage.utils'
import { safeGetJsonItem, safeSetJsonItem } from '@/shared/utils/safeStorage'
import { useNotification } from '@/shared/hooks/useNotification'
import { appLogger } from '@/shared/utils/logger'
import { getErrorMessage } from '@/shared/utils/errorMessages'

const GeneralSettings = lazy(() => import('@/features/settings/components/GeneralSettings').then(m => ({ default: m.GeneralSettings })))

interface Settings {
  theme: string
  language: string
  apiProvider: string
  apiKey: string
  promptContent: string
  requireConfirm: boolean
  enableAudit: boolean
  maxToolCallRounds: number
}

interface RemoteModelCacheEntry {
  signature: string
  fetchedAt: number
  options: Array<{
    id: string
    provider: string
    model: string
    display_name: string
  }>
}

export function GeneralTabContainer() {
  const { message, showNotification } = useNotification(3000)

  // 通用设置状态
  const [settings, setSettings] = useState<Settings>({
    theme: 'light',
    language: 'zh',
    apiProvider: 'openai',
    apiKey: '',
    promptContent: '',
    requireConfirm: true,
    enableAudit: true,
    maxToolCallRounds: 12,
  })
  const [, setSaving] = useState(false)

  // 共享数据
  const {
    configurations,
    loadModelsData,
  } = useSharedSettingsData()

  // 全局模型选择
  const {
    selectedModel: globalSelectedModel,
    setSelectedModel: setGlobalSelectedModel,
    modelOptions,
    setModelOptions,
    modelLoading,
    setModelLoading,
    modelError,
    setModelError,
    outputMode,
    setOutputMode,
  } = useGlobalModelSelection()

  // 模型参数编辑状态
  const [selectedConfigModelOptionKey, setSelectedConfigModelOptionKey] = useState('')
  const [modelCapabilities, setModelCapabilities] = useState<ModelCapabilitiesResponse | null>(null)
  const [editingTemperature, setEditingTemperature] = useState(0.7)
  const [editingTopK, setEditingTopK] = useState(0.9)
  const [editingMaxTokensLimit, setEditingMaxTokensLimit] = useState<number | ''>('')
  const [savingModelParams, setSavingModelParams] = useState(false)
  const [hasAttemptedGlobalModelLoad, setHasAttemptedGlobalModelLoad] = useState(false)
  const [globalModelLoadSummary, setGlobalModelLoadSummary] = useState<string | null>(null)
  const remoteModelCacheRef = useRef<Map<string, RemoteModelCacheEntry>>(new Map())

  // 计费数据
  const [models, setModels] = useState<ModelPricing[]>([])
  const [, setLoadingModels] = useState(false)

  /** 加载本地保存的设置 */
  const loadSettings = useCallback(() => {
    const savedSettings = safeGetJsonItem<unknown>('app_settings', null)
    if (savedSettings && isPersistedSettings(savedSettings)) {
      const normalizedRounds = typeof savedSettings.maxToolCallRounds === 'number'
        ? Math.max(1, Math.min(50000, Math.trunc(savedSettings.maxToolCallRounds)))
        : undefined
      setSettings((prev) => ({
        ...prev,
        ...savedSettings,
        maxToolCallRounds: normalizedRounds ?? prev.maxToolCallRounds,
      }))
      return
    }
    if (savedSettings) {
      appLogger.error({ event: 'settings_load_failed', message: 'Failed to load settings', module: 'settings' })
    }
  }, [])

  /** 加载提示词 */
  const loadPrompts = useCallback(async () => {
    try {
      const response = await promptsAPI.getActive()
      if (response.data && response.data.content) {
        setSettings(prev => ({ ...prev, promptContent: response.data.content }))
      }
    } catch (error) {
      appLogger.error({ event: 'prompts_load_failed', message: 'Failed to load prompts', module: 'settings' })
    }
  }, [])

  /** 加载计费数据 */
  const loadBillingData = useCallback(async () => {
    setLoadingModels(true)
    try {
      const modelsRes = await billingAPI.getModels()
      setModels(modelsRes.data.models || [])
    } catch {
      appLogger.error({ event: 'billing_data_load_failed', message: 'Failed to load billing data', module: 'settings' })
    } finally {
      setLoadingModels(false)
    }
  }, [])

  /** 构建供应商缓存签名 */
  const buildProviderCacheSignature = useCallback((provider: ModelProvider) => {
    return [
      provider.id,
      provider.base_url || provider.api_endpoint || '',
      provider.has_api_key ? 'with-key' : 'without-key',
      String(provider.configuration_count || 0),
    ].join('|')
  }, [])

  /** 构建远端模型选项 */
  const buildRemoteModelOptions = useCallback((provider: { id: string; display_name?: string; name?: string }, remoteModels: Array<{ model: string }>) => {
    const displayProvider = provider.display_name || provider.name || provider.id
    const uniqueModels = Array.from(new Set(remoteModels.map((item) => item.model).filter(Boolean)))

    return uniqueModels.map((modelName) => ({
      id: `${provider.id}:${modelName}`,
      provider: provider.id,
      model: modelName,
      display_name: `${displayProvider} - ${modelName}`,
    }))
  }, [])

  /** 加载全局模型选项 */
  const loadGlobalModelOptions = useCallback(async () => {
    setHasAttemptedGlobalModelLoad(true)
    setModelLoading(true)
    setModelError(null)
    setGlobalModelLoadSummary(null)
    try {
      const response = await modelsAPI.getProviders()
      const providersList: ModelProvider[] = response.data.providers || []
      const validProviders = providersList.filter((provider) => (provider.configuration_count || 0) > 0)

      if (validProviders.length === 0) {
        setModelOptions([])
        setGlobalModelLoadSummary('暂无已配置的供应商，请先前往 API 配置添加并保存供应商。')
        return
      }

      const providerResults = await Promise.all(validProviders.map(async (provider: ModelProvider) => {
        const signature = buildProviderCacheSignature(provider)
        const cached = remoteModelCacheRef.current.get(provider.id)
        const cacheValid = cached &&
          cached.signature === signature &&
          Date.now() - cached.fetchedAt < REMOTE_MODEL_CACHE_TTL_MS

        if (cacheValid) {
          return {
            provider,
            options: cached.options,
            ignoredLocalFallback: false,
            emptyRemoteResult: cached.options.length === 0,
          }
        }

        const providerModelsResponse = await modelsAPI.getModelsByProvider(provider.id)
        const providerModelsData = providerModelsResponse.data

        if (providerModelsData.source !== 'remote') {
          remoteModelCacheRef.current.delete(provider.id)
          return {
            provider,
            options: [],
            ignoredLocalFallback: true,
            emptyRemoteResult: false,
          }
        }

        const options = buildRemoteModelOptions(provider, providerModelsData.models || [])
        remoteModelCacheRef.current.set(provider.id, {
          signature,
          fetchedAt: Date.now(),
          options,
        })

        return {
          provider,
          options,
          ignoredLocalFallback: false,
          emptyRemoteResult: options.length === 0,
        }
      }))

      const nextOptions = providerResults
        .flatMap((result) => result.options)
        .sort((left, right) => left.display_name.localeCompare(right.display_name, 'zh-CN'))

      setModelOptions(nextOptions)

      if (!globalSelectedModel) {
        if (configurations.length > 0) {
          const defaultConfig = configurations.find((config) => config.is_default) || configurations[0]
          const defaultModelName = defaultConfig.selected_models?.[0] || defaultConfig.model
          setGlobalSelectedModel(`${defaultConfig.provider}:${defaultModelName}`)
        } else if (nextOptions.length > 0) {
          setGlobalSelectedModel(nextOptions[0].id)
        }
      }

      const ignoredProviders = providerResults
        .filter((result) => result.ignoredLocalFallback)
        .map((result) => result.provider.display_name || result.provider.name || result.provider.id)
      const emptyProviders = providerResults
        .filter((result) => result.emptyRemoteResult)
        .map((result) => result.provider.display_name || result.provider.name || result.provider.id)

      if (ignoredProviders.length > 0 || emptyProviders.length > 0) {
        const messages: string[] = []
        if (ignoredProviders.length > 0) {
          messages.push(`以下供应商未返回远端模型，已忽略本地回退结果：${ignoredProviders.join('、')}`)
        }
        if (emptyProviders.length > 0) {
          messages.push(`以下供应商当前未返回可用远端模型：${emptyProviders.join('、')}`)
        }
        setGlobalModelLoadSummary(messages.join('；'))
      } else if (nextOptions.length === 0) {
        setGlobalModelLoadSummary('当前已配置供应商暂未返回可用远端模型，请检查基础 URL、API Key 或稍后重试。')
      }
    } catch (err) {
      appLogger.error({
        event: 'global_model_load',
        module: 'settings',
        action: 'load_model_options',
        status: 'failure',
        message: 'failed to load model configurations for global selector',
        extra: { error: err instanceof Error ? err.message : String(err) },
      })
      setModelError('加载模型失败，请检查网络连接')
      setModelOptions([])
    } finally {
      setModelLoading(false)
    }
  }, [configurations, globalSelectedModel, setGlobalSelectedModel, setModelOptions, setModelLoading, setModelError, buildProviderCacheSignature, buildRemoteModelOptions])

  /** 选择模型配置 */
  const handleSelectModelConfig = useCallback(async (optionKey: string) => {
    setSelectedConfigModelOptionKey(optionKey)
    const [configIdText, modelName] = optionKey.split(':')
    const configId = Number(configIdText)
    const config = configurations.find(c => c.id === configId)

    if (config && modelName) {
      setGlobalSelectedModel(`${config.provider}:${modelName}`)
      appLogger.info({ event: 'global_model_change', module: 'settings', action: 'change_default_model_from_param_panel', status: 'success', message: 'default model changed via param panel', extra: { model: `${config.provider}:${modelName}` } })
    }

    try {
      const capRes = await modelsAPI.getCapabilities(configId)
      setModelCapabilities(capRes.data)
      setEditingTemperature(config?.temperature ?? capRes.data.defaults.temperature)
      setEditingTopK(config?.top_k ?? capRes.data.defaults.top_k)
      setEditingMaxTokensLimit(config?.max_tokens_limit ?? '')
    } catch {
      setModelCapabilities(null)
      setEditingTemperature(config?.temperature ?? 0.7)
      setEditingTopK(config?.top_k ?? 0.9)
      setEditingMaxTokensLimit(config?.max_tokens_limit ?? '')
    }
  }, [configurations, setGlobalSelectedModel])

  /** 保存模型参数 */
  const handleSaveModelParams = useCallback(async () => {
    const selectedConfigModelOption = configurations.flatMap(c =>
      (c.selected_models?.length ? c.selected_models : [c.model]).map(m => ({
        key: `${c.id}:${m}`,
        configId: c.id,
      }))
    ).find(opt => opt.key === selectedConfigModelOptionKey)

    if (!selectedConfigModelOption) return
    setSavingModelParams(true)
    try {
      await modelsAPI.updateParameters(selectedConfigModelOption.configId, {
        temperature: editingTemperature,
        top_k: editingTopK,
        max_tokens_limit: editingMaxTokensLimit === '' ? null : editingMaxTokensLimit,
      })
      showNotification({ type: 'success', text: '模型参数保存成功' })
      await loadModelsData()
    } catch (error) {
      showNotification({ type: 'error', text: getErrorMessage(error, '模型参数保存失败') })
    } finally {
      setSavingModelParams(false)
    }
  }, [configurations, selectedConfigModelOptionKey, editingTemperature, editingTopK, editingMaxTokensLimit, showNotification, loadModelsData])

  /** 重置模型参数 */
  const handleResetModelParams = useCallback(async () => {
    const selectedConfigModelOption = configurations.flatMap(c =>
      (c.selected_models?.length ? c.selected_models : [c.model]).map(m => ({
        key: `${c.id}:${m}`,
        configId: c.id,
      }))
    ).find(opt => opt.key === selectedConfigModelOptionKey)

    if (!selectedConfigModelOption) return
    setSavingModelParams(true)
    try {
      const res = await modelsAPI.resetParameters(selectedConfigModelOption.configId)
      const config = res.data.configuration
      setEditingTemperature(config?.temperature ?? 0.7)
      setEditingTopK(config?.top_k ?? 0.9)
      setEditingMaxTokensLimit(config?.max_tokens_limit ?? '')
      showNotification({ type: 'success', text: '已重置为默认参数' })
      await loadModelsData()
    } catch (error) {
      showNotification({ type: 'error', text: getErrorMessage(error, '重置失败') })
    } finally {
      setSavingModelParams(false)
    }
  }, [configurations, selectedConfigModelOptionKey, showNotification, loadModelsData])

  /** 保存设置 */
  const saveSettings = useCallback(async () => {
    setSaving(true)
    try {
      safeSetJsonItem('app_settings', buildPersistedSettings(settings))
      userAPI.updatePreferences({
        theme: settings.theme,
        language: settings.language,
        apiProvider: settings.apiProvider,
        requireConfirm: settings.requireConfirm,
        enableAudit: settings.enableAudit,
        maxToolCallRounds: settings.maxToolCallRounds,
      }).catch((error) => {
        appLogger.error({ event: 'preferences_sync_failed', module: 'settings', message: '用户偏好同步失败', extra: { error: error instanceof Error ? error.message : String(error) } })
      })

      if (settings.promptContent) {
        const existingPrompts = await promptsAPI.getAll()
        if (existingPrompts.data && existingPrompts.data.length > 0) {
          await promptsAPI.update(existingPrompts.data[0].id, {
            name: 'System Prompt',
            content: settings.promptContent,
            variables: '{}',
            is_active: true
          })
        } else {
          await promptsAPI.create({
            name: 'System Prompt',
            content: settings.promptContent,
            variables: '{}',
          })
        }
      }

      showNotification({ type: 'success', text: '设置保存成功' })
    } catch (error) {
      showNotification({ type: 'error', text: getErrorMessage(error, '保存失败，请重试') })
    } finally {
      setSaving(false)
    }
  }, [settings, showNotification])

  /** 设置变更 */
  const handleChange = useCallback(<K extends keyof Settings>(key: K, value: Settings[K]) => {
    setSettings(prev => ({ ...prev, [key]: value }))
  }, [])

  // 首次挂载时加载数据
  useEffect(() => {
    loadSettings()
    loadPrompts()
    loadModelsData()
    loadBillingData()
  }, [loadSettings, loadPrompts, loadModelsData, loadBillingData])

  // 自动选择默认模型配置
  useEffect(() => {
    if (configurations.length > 0 && !selectedConfigModelOptionKey) {
      const defaultConfig = configurations.find((config) => config.is_default) || configurations[0]
      const defaultModelName = defaultConfig.selected_models?.[0] || defaultConfig.model
      handleSelectModelConfig(`${defaultConfig.id}:${defaultModelName}`)
    }
  }, [configurations, selectedConfigModelOptionKey, handleSelectModelConfig])

  return (
    <>
      {message && (
        <div className={`message ${message.type}`}>
          {message.text}
        </div>
      )}
      <Suspense fallback={<div style={{ padding: '2rem', textAlign: 'center', color: '#9ca3af' }}>加载中...</div>}>
        <GeneralSettings
          settings={settings}
          outputMode={outputMode}
          globalSelectedModel={globalSelectedModel}
          modelOptions={modelOptions}
          hasAttemptedGlobalModelLoad={hasAttemptedGlobalModelLoad}
          globalModelLoadSummary={globalModelLoadSummary}
          modelLoading={modelLoading}
          modelError={modelError}
          configurations={configurations}
          selectedConfigModelOptionKey={selectedConfigModelOptionKey}
          editingTemperature={editingTemperature}
          editingTopK={editingTopK}
          editingMaxTokensLimit={editingMaxTokensLimit}
          modelCapabilities={modelCapabilities}
          models={models}
          savingModelParams={savingModelParams}
          onSettingChange={handleChange}
          onOutputModeChange={setOutputMode}
          onGlobalModelChange={setGlobalSelectedModel}
          onLoadGlobalModelOptions={loadGlobalModelOptions}
          onSelectModelConfig={handleSelectModelConfig}
          onSaveModelParams={handleSaveModelParams}
          onResetModelParams={handleResetModelParams}
          onSave={saveSettings}
        />
      </Suspense>
    </>
  )
}
