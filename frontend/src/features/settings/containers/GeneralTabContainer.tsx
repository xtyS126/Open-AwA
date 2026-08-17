/**
 * 通用设置 Tab 容器组件
 * 管理通用设置相关的所有状态和数据获取逻辑
 *
 * 改造说明（fix-performance-remaining-issues 模块 C）：
 *   - 原实现使用 useEffect + axios，每次 mount 都触发 /api/billing/models、/api/prompts/active、
 *     /api/billing/configurations/{id}/capabilities 请求
 *   - 现改用 useQuery + queryClient.invalidateQueries，多 Tab 切换时复用缓存
 *   - queryKey 约定：
 *     - ['billing', 'models']：与 BillingTabContainer 共享
 *     - ['prompts', 'active']：与 PromptsTabContainer 共享
 *     - ['billing', 'configurations', configId, 'capabilities']：按 configId 缓存
 *   - 保留 loadServerPreferences 5 秒节流入口（fix-preferences-deadloop spec 成果）
 *   - 保留 useSharedSettingsData 的 loadModelsData（configurations/providers 加载，已正确实现）
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { lazy, Suspense } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
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
import { loadServerPreferences } from '@/shared/utils/preferenceSync'
import { useNotification } from '@/shared/hooks/useNotification'
import { appLogger } from '@/shared/utils/logger'
import { getErrorMessage } from '@/shared/utils/errorMessages'
import { Skeleton } from '@/shared/components/ui/Skeleton'
import { BILLING_MODELS_QUERY_KEY } from './BillingTabContainer'

const GeneralSettings = lazy(() => import('@/features/settings/components/GeneralSettings').then(m => ({ default: m.GeneralSettings })))

/** 活跃提示词查询的 queryKey，供 PromptsTabContainer 共享缓存 */
export const PROMPTS_ACTIVE_QUERY_KEY = ['prompts', 'active'] as const

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
  const queryClient = useQueryClient()

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

  // 共享数据（configurations / providers，由 useSharedSettingsStore 管理 5min stale-while-revalidate）
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

  // 计费数据（模型价格列表）—— 与 BillingTabContainer 共享 ['billing', 'models'] 缓存
  // 不使用 initialData：否则 staleTime 内 React Query 会将初始值视为新鲜数据而不发起请求
  const { data: models } = useQuery<ModelPricing[]>({
    queryKey: BILLING_MODELS_QUERY_KEY,
    queryFn: () => billingAPI.getModels().then(r => r.data.models || []),
  })

  // 活跃提示词 —— 与 PromptsTabContainer 共享 ['prompts', 'active'] 缓存
  const { data: activePrompt } = useQuery({
    queryKey: PROMPTS_ACTIVE_QUERY_KEY,
    queryFn: () => promptsAPI.getActive().then(r => r.data),
  })

  // 提示词加载完成后同步到 settings.promptContent（首次加载与保存后刷新均会触发）
  useEffect(() => {
    if (activePrompt?.content) {
      setSettings(prev => ({ ...prev, promptContent: activePrompt.content }))
    }
  }, [activePrompt])

  // 当前选中的 configId（从 optionKey 解析，供 capabilities 查询使用）
  const selectedConfigId = selectedConfigModelOptionKey
    ? Number(selectedConfigModelOptionKey.split(':')[0])
    : null

  // 模型能力查询：按 configId 缓存，configId 为空时禁用查询
  const { data: capabilitiesData } = useQuery({
    queryKey: ['billing', 'configurations', selectedConfigId, 'capabilities'],
    queryFn: () => modelsAPI.getCapabilities(selectedConfigId as number).then(r => r.data),
    enabled: !!selectedConfigId,
  })

  // 能力数据加载完成后同步 modelCapabilities 与编辑参数
  // 与原实现一致：优先用 config 中保存的值，回退到 capabilities.defaults
  useEffect(() => {
    if (!selectedConfigId) {
      setModelCapabilities(null)
      return
    }
    const config = configurations.find(c => c.id === selectedConfigId)
    if (capabilitiesData) {
      setModelCapabilities(capabilitiesData)
      setEditingTemperature(config?.temperature ?? capabilitiesData.defaults.temperature)
      setEditingTopK(config?.top_k ?? capabilitiesData.defaults.top_k)
      setEditingMaxTokensLimit(config?.max_tokens_limit ?? '')
    } else if (!capabilitiesData && config) {
      // 查询加载中或失败时，保留 config 中的值作为回退
      setEditingTemperature(config.temperature ?? 0.7)
      setEditingTopK(config.top_k ?? 0.9)
      setEditingMaxTokensLimit(config.max_tokens_limit ?? '')
    }
  }, [capabilitiesData, configurations, selectedConfigId])

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

  /** 从后端拉取用户偏好覆盖本地（实现多端同步）
   *  触发场景：localStorage 加载完成后，异步从后端 /user/preferences 拉取最新偏好。
   *  优先级：后端 > localStorage > 默认值
   *  设计权衡：
   *  - 本地优先快速显示，避免阻塞 UI
   *  - 后端覆盖以最新为准，解决多端同步与数据库重置后 localStorage 残留旧值问题
   *  - 失败静默（保留本地值），不中断 UI
   *  - 复用 loadServerPreferences 的 5 秒节流，避免与 App 启动期重复拉取 /api/user/preferences
   */
  const syncSettingsFromServer = useCallback(async () => {
    try {
      // 复用 loadServerPreferences 的 5 秒节流，避免与 App 启动期重复拉取 /api/user/preferences
      const prefs = await loadServerPreferences()
      if (!prefs || typeof prefs !== 'object') {
        return
      }
      // 仅覆盖后端实际存在的字段，保留本地未同步的字段
      const serverOverride: Partial<typeof settings> = {}
      if (typeof prefs.theme === 'string') serverOverride.theme = prefs.theme
      if (typeof prefs.language === 'string') serverOverride.language = prefs.language
      if (typeof prefs.apiProvider === 'string') serverOverride.apiProvider = prefs.apiProvider
      if (typeof prefs.requireConfirm === 'boolean') serverOverride.requireConfirm = prefs.requireConfirm
      if (typeof prefs.enableAudit === 'boolean') serverOverride.enableAudit = prefs.enableAudit
      if (typeof prefs.maxToolCallRounds === 'number') {
        serverOverride.maxToolCallRounds = Math.max(1, Math.min(50000, Math.trunc(prefs.maxToolCallRounds)))
      }
      if (Object.keys(serverOverride).length > 0) {
        // 使用 functional update 读取最新本地状态，避免依赖 settings state 导致无限循环
        setSettings((prev) => {
          const next = { ...prev, ...serverOverride }
          // 同步回写 localStorage，确保下次启动时本地与后端一致
          safeSetJsonItem('app_settings', buildPersistedSettings(next))
          return next
        })
      }
    } catch (error) {
      appLogger.warning({
        event: 'preferences_fetch_failed',
        module: 'settings',
        message: '从后端同步偏好失败，保留本地值',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
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
      const validProviders = providersList.filter((provider) => (provider.configuration_count || 0) > 0 && provider.has_api_key === true)

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

      // 校验当前选中模型是否仍在新加载的模型列表中
      // 场景：数据库重置后 localStorage 仍保留旧模型名（如 deepseek-v4-flash），
      // 但该模型已不在后端 model_configurations 表中，需自动切换到有效模型
      const isCurrentModelValid = globalSelectedModel &&
        nextOptions.some((opt) => opt.id === globalSelectedModel)

      if (!globalSelectedModel || !isCurrentModelValid) {
        if (configurations.length > 0) {
          // 优先使用后端标记为 is_default 的配置
          const defaultConfig = configurations.find((config) => config.is_default) || configurations[0]
          const defaultModelName = defaultConfig.selected_models?.[0] || defaultConfig.model
          setGlobalSelectedModel(`${defaultConfig.provider}:${defaultModelName}`)
        } else if (nextOptions.length > 0) {
          // 回退到第一个可用模型
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

  /** 选择模型配置
   *  改造后：仅设置 optionKey 与 globalSelectedModel，capabilities 由 useQuery 自动拉取
   */
  const handleSelectModelConfig = useCallback((optionKey: string) => {
    setSelectedConfigModelOptionKey(optionKey)
    const [configIdText, modelName] = optionKey.split(':')
    const configId = Number(configIdText)
    const config = configurations.find(c => c.id === configId)

    if (config && modelName) {
      setGlobalSelectedModel(`${config.provider}:${modelName}`)
      appLogger.info({ event: 'global_model_change', module: 'settings', action: 'change_default_model_from_param_panel', status: 'success', message: 'default model changed via param panel', extra: { model: `${config.provider}:${modelName}` } })
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
      // 失效 configurations 缓存（useSharedSettingsStore 内部状态）与 capabilities 缓存
      await loadModelsData()
      await queryClient.invalidateQueries({
        queryKey: ['billing', 'configurations', selectedConfigModelOption.configId, 'capabilities'],
      })
    } catch (error) {
      showNotification({ type: 'error', text: getErrorMessage(error, '模型参数保存失败') })
    } finally {
      setSavingModelParams(false)
    }
  }, [configurations, selectedConfigModelOptionKey, editingTemperature, editingTopK, editingMaxTokensLimit, showNotification, loadModelsData, queryClient])

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
      // 失效 configurations 缓存与 capabilities 缓存
      await loadModelsData()
      await queryClient.invalidateQueries({
        queryKey: ['billing', 'configurations', selectedConfigModelOption.configId, 'capabilities'],
      })
    } catch (error) {
      showNotification({ type: 'error', text: getErrorMessage(error, '重置失败') })
    } finally {
      setSavingModelParams(false)
    }
  }, [configurations, selectedConfigModelOptionKey, showNotification, loadModelsData, queryClient])

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
        // 失效提示词缓存，触发 useQuery 重新拉取最新活跃提示词
        await queryClient.invalidateQueries({ queryKey: PROMPTS_ACTIVE_QUERY_KEY })
      }

      showNotification({ type: 'success', text: '设置保存成功' })
    } catch (error) {
      showNotification({ type: 'error', text: getErrorMessage(error, '保存失败，请重试') })
    } finally {
      setSaving(false)
    }
  }, [settings, showNotification, queryClient])

  /** 设置变更 */
  const handleChange = useCallback(<K extends keyof Settings>(key: K, value: Settings[K]) => {
    setSettings(prev => ({ ...prev, [key]: value }))
  }, [])

  // 首次挂载时加载本地设置、共享配置数据、同步后端偏好
  // loadBillingData 与 loadPrompts 已由 useQuery 接管，无需在此调用
  useEffect(() => {
    loadSettings()
    loadModelsData()
    // 异步从后端同步偏好（不 await，本地优先快速显示，后端覆盖在后）
    void syncSettingsFromServer()
  }, [loadSettings, loadModelsData, syncSettingsFromServer])

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
      <Suspense fallback={(
        <div style={{ padding: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <Skeleton variant="rectangular" height="var(--space-10)" width="40%" />
          <Skeleton.Paragraph lines={6} />
        </div>
      )}>
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
          models={models || []}
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
