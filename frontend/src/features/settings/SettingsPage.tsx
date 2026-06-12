import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  Settings as SettingsIcon,
  ShieldAlert,
  Cpu,
  Briefcase,
  Plug,
  HardDrive,
  Key,
  Sliders,
} from 'lucide-react'
import PageLayout from '@/shared/components/PageLayout/PageLayout'
import { promptsAPI, conversationAPI, ConversationRecordItem, ConversationCollectionStatusResponse, getApiErrorDetail, userAPI } from '@/shared/api/api'
import { billingAPI, ModelPricing, RetentionConfig } from '@/features/billing/billingApi'
import { modelsAPI, ModelConfiguration, ModelProvider, ProviderDetailResponse, ProviderModel, ProviderModelsResponse, ModelCapabilitiesResponse, OllamaModel, ProviderConnectionStatus } from '@/features/settings/modelsApi'
import type { ModelEditParams } from '@/features/settings/components/ModelParameterEditor'
import { useChatStore } from '@/features/chat/store/chatStore'
import type { ModelOption } from '@/features/chat/store/chatStore'
import { useNotification } from '@/shared/hooks/useNotification'
import { appLogger } from '@/shared/utils/logger'
import { safeGetJsonItem, safeSetJsonItem } from '@/shared/utils/safeStorage'
import styles from './SettingsPage.module.css'


// 懒加载非核心 Tab 组件（MCP）
const MCPSettings = lazy(() => import('./MCPSettings'))
const SecuritySettings = lazy(() => import('./SecuritySettings'))
const PermissionSettings = lazy(() => import('./PermissionSettings'))
const EnvVarSettings = lazy(() => import('./EnvVarSettings'))

// 物理抽离的子组件（静态导入）
import { DataRetentionTab } from './components/DataRetentionTab'
import { PromptsTab } from './components/PromptsTab'
import { BillingTab } from './components/BillingTab'
import { DataCollectionTab } from './components/DataCollectionTab'
import { GeneralSettings } from './components/GeneralSettings'
import { ModelsTab } from './components/ModelsTab'
import { ApiSettings } from './components/ApiSettings'
import { CreateProviderModal } from './modals/CreateProviderModal'
import { DeleteConfirmModal } from './modals/DeleteConfirmModal'
import { ImportModelsModal } from './modals/ImportModelsModal'
import { DeleteModelsModal } from './modals/DeleteModelsModal'
import {
  REMOTE_MODEL_CACHE_TTL_MS,
  normalizeProviderId,
  normalizeProviderBaseUrl,
  buildModelEditParams,
  buildPersistedSettings,
  isPersistedSettings,
} from './SettingsPage.utils'

/** 懒加载组件的加载占位符 */
function TabLoadingFallback() {
  return <div style={{ padding: '2rem', textAlign: 'center', color: '#9ca3af' }}>加载中...</div>
}

// 已知供应商显示名称由 @/assets/providers 统一提供，参见 PROVIDER_NAMES 与 getProviderDisplayName()

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

// isPersistedSettings、buildPersistedSettings、PersistedSettings 类型已从 SettingsPage.utils 导入

interface ApiProviderFormState {
  config_id: number | null
  provider: string
  display_name: string
  icon: string
  api_endpoint: string
  api_key: string
  has_api_key: boolean
  selected_models: string[]
}

interface AddProviderFormState {
  provider: string
  display_name: string
  api_endpoint: string
  is_custom: boolean
}

interface ConfigModelOption {
  key: string
  configId: number
  provider: string
  providerDisplayName: string
  modelName: string
  configuration: ModelConfiguration
}

interface RemoteModelCacheEntry {
  signature: string
  fetchedAt: number
  options: ModelOption[]
}

function SettingsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const queryParams = new URLSearchParams(location.search)
  const initialTab = queryParams.get('tab') || 'general'

  const createInitialAddProviderForm = (): AddProviderFormState => ({
    provider: '',
    display_name: '',
    api_endpoint: '',
    is_custom: false
  })

  const [activeTab, setActiveTab] = useState(initialTab)

  useEffect(() => {
    const tab = queryParams.get('tab')
    if (tab === 'communication') {
      navigate('/communication', { replace: true })
      return
    }
    if (tab && tab !== activeTab) {
      setActiveTab(tab)
    } else if (!tab && activeTab !== 'general') {
      setActiveTab('general')
    }
  }, [location.search, navigate])

  const handleTabChange = (tab: string) => {
    setActiveTab(tab)
    if (tab === 'general') {
      navigate('/settings')
    } else {
      navigate(`/settings?tab=${tab}`)
    }
  }
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
  const [saving, setSaving] = useState(false)
  const { message, showNotification } = useNotification(3000)
  const [models, setModels] = useState<ModelPricing[]>([])
  const [loadingModels, setLoadingModels] = useState(false)
  const [editingModel, setEditingModel] = useState<number | null>(null)
  const [editPrices, setEditPrices] = useState({ input_price: '', output_price: '' })
  const [retentionConfig, setRetentionConfig] = useState<RetentionConfig | null>(null)
  const [retentionDays, setRetentionDays] = useState(365)
  const [cleanupOld, setCleanupOld] = useState(false)
  const [loadingRetention, setLoadingRetention] = useState(false)

  const [configurations, setConfigurations] = useState<ModelConfiguration[]>([])
  const [loadingConfigs, setLoadingConfigs] = useState(false)
  const [providers, setProviders] = useState<ModelProvider[]>([])
  const providerNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    providers.forEach((p) => {
      map[p.id] = p.display_name || p.name || p.id
    })
    return map
  }, [providers])
  const [providerModels, setProviderModels] = useState<ProviderModel[]>([])
  const [showAddForm, setShowAddForm] = useState(false)
  const [newConfig, setNewConfig] = useState({
    provider: '',
    model: '',
    display_name: '',
    description: '',
    is_default: false,
  })

  // 模型编辑模态框状态
  const [editingConfigId, setEditingConfigId] = useState<number | null>(null)
  const [editConfigForm, setEditConfigForm] = useState({
    display_name: '',
    description: '',
    input_modality: ['text'] as string[],
    output_modality: ['text'] as string[],
  })
  const [savingConfigEdit, setSavingConfigEdit] = useState(false)

  // Model parameter panel state
  const [selectedConfigModelOptionKey, setSelectedConfigModelOptionKey] = useState('')
  const [modelCapabilities, setModelCapabilities] = useState<ModelCapabilitiesResponse | null>(null)
  const [editingTemperature, setEditingTemperature] = useState(0.7)
  const [editingTopK, setEditingTopK] = useState(0.9)
  const [editingMaxTokensLimit, setEditingMaxTokensLimit] = useState<number | ''>('')
  const [savingModelParams, setSavingModelParams] = useState(false)
  const [hasAttemptedGlobalModelLoad, setHasAttemptedGlobalModelLoad] = useState(false)
  const [globalModelLoadSummary, setGlobalModelLoadSummary] = useState<string | null>(null)
  const remoteModelCacheRef = useRef<Map<string, RemoteModelCacheEntry>>(new Map())

  // ── 模型独立配置卡片状态 ────────────────────────────────────────
  // 记录当前展开的模型配置卡片集合（按 "provider:model" 键）
  const [expandedModelConfigs, setExpandedModelConfigs] = useState<Set<string>>(new Set())
  // 每个模型当前的编辑参数（按 "modelName" 键）
  const [modelEditParams, setModelEditParams] = useState<Record<string, ModelEditParams>>({})
  // 每个模型的保存状态
  const [savingModelConfig, setSavingModelConfig] = useState<Record<string, boolean>>({})
  // 正在加载 capabilities 的模型集合，防止快速双击触发重复请求
  const loadingCapsRef = useRef<Set<string>>(new Set())

  // buildModelEditParams 已从 SettingsPage.utils 导入

  const [selectedProviderId, setSelectedProviderId] = useState('')
  const [loadingApiProviders, setLoadingApiProviders] = useState(false)
  const [loadingProviderDetail, setLoadingProviderDetail] = useState(false)
  const [loadingProviderModels, setLoadingProviderModels] = useState(false)
  const [providerModelsError, setProviderModelsError] = useState<string | null>(null)
  const [showCreateProviderModal, setShowCreateProviderModal] = useState(false)
  const [showDeleteConfirmModal, setShowDeleteConfirmModal] = useState(false)
  const [creatingProvider, setCreatingProvider] = useState(false)
  const [deletingProvider, setDeletingProvider] = useState(false)

  // --- New states for model importing and batch deleting ---
  const [showImportModal, setShowImportModal] = useState(false)
  const [fetchedRemoteModels, setFetchedRemoteModels] = useState<ProviderModel[]>([])
  const [modalSelectedModels, setModalSelectedModels] = useState<string[]>([])
  const [importing, setImporting] = useState(false)
  const [selectedForDeletion, setSelectedForDeletion] = useState<string[]>([])
  const [showDeleteModelsModal, setShowDeleteModelsModal] = useState(false)
  const [deletingModels, setDeletingModels] = useState(false)
  // --------------------------------------------------------

  const [addProviderForm, setAddProviderForm] = useState(createInitialAddProviderForm())

  // Ollama 模型发现相关状态
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([])
  const [loadingOllama, setLoadingOllama] = useState(false)
  const [ollamaError, setOllamaError] = useState<string | null>(null)
  // 提供商连接状态
  const [providerStatuses, setProviderStatuses] = useState<ProviderConnectionStatus[]>([])
  const [loadingProviderStatuses, setLoadingProviderStatuses] = useState(false)

  const [providerForm, setProviderForm] = useState<ApiProviderFormState>({
    config_id: null,
    provider: '',
    display_name: '',
    icon: '',
    api_endpoint: '',
    api_key: '',
    has_api_key: false,
    selected_models: []
  })
  const providerApiKeyInputRef = useRef<HTMLInputElement | null>(null)

  const [collectionEnabled, setCollectionEnabled] = useState(false)
  const [collectionStats, setCollectionStats] = useState<ConversationCollectionStatusResponse['stats'] | null>(null)
  const [updatingCollection, setUpdatingCollection] = useState(false)
  const [recordsPreview, setRecordsPreview] = useState<ConversationRecordItem[]>([])
  const [loadingRecordsPreview, setLoadingRecordsPreview] = useState(false)
  const [exportStartTime, setExportStartTime] = useState('')
  const [exportEndTime, setExportEndTime] = useState('')
  const [exportingRecords, setExportingRecords] = useState(false)
  const [cleanupDays, setCleanupDays] = useState(30)
  const [cleaningRecords, setCleaningRecords] = useState(false)

  // 全局模型选择状态（来自 chatStore）
  const { selectedModel: globalSelectedModel, setSelectedModel: setGlobalSelectedModel, modelOptions, setModelOptions, modelLoading, setModelLoading, modelError, setModelError, outputMode, setOutputMode } = useChatStore()

  const configModelOptions = useMemo<ConfigModelOption[]>(() => {
    return configurations.flatMap((configuration) => {
      const providerDisplayName = providerNameMap[configuration.provider] || configuration.provider
      const candidateModels = configuration.selected_models && configuration.selected_models.length > 0
        ? configuration.selected_models
        : [configuration.model]

      return candidateModels.map((modelName) => ({
        key: `${configuration.id}:${modelName}`,
        configId: configuration.id,
        provider: configuration.provider,
        providerDisplayName,
        modelName,
        configuration,
      }))
    })
  }, [configurations, providerNameMap])

  const selectedConfigModelOption = useMemo(
    () => configModelOptions.find((option) => option.key === selectedConfigModelOptionKey) ?? null,
    [configModelOptions, selectedConfigModelOptionKey]
  )

  const resetGlobalModelOptionsState = () => {
    setHasAttemptedGlobalModelLoad(false)
    setGlobalModelLoadSummary(null)
    setModelOptions([])
    setModelError(null)
  }

  const invalidateRemoteModelCache = (providerId?: string) => {
    if (providerId) {
      remoteModelCacheRef.current.delete(providerId)
    } else {
      remoteModelCacheRef.current.clear()
    }
    resetGlobalModelOptionsState()
  }

  const buildProviderCacheSignature = (provider: ModelProvider): string => {
    return [
      provider.id,
      provider.base_url || provider.api_endpoint || '',
      provider.has_api_key ? 'with-key' : 'without-key',
      String(provider.configuration_count || 0),
    ].join('|')
  }

  const buildRemoteModelOptions = (provider: ModelProvider, remoteModels: ProviderModel[]): ModelOption[] => {
    const displayProvider = provider.display_name || provider.name || provider.id
    const uniqueModels = Array.from(new Set(remoteModels.map((item) => item.model).filter(Boolean)))

    return uniqueModels.map((modelName) => ({
      id: `${provider.id}:${modelName}`,
      provider: provider.id,
      model: modelName,
      display_name: `${displayProvider} - ${modelName}`,
    }))
  }

  // 加载可用远端模型列表（供通用设置页模型选择器使用）
  const loadGlobalModelOptions = async () => {
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

      const providerResults = await Promise.all(validProviders.map(async (provider) => {
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
        const providerModelsData = providerModelsResponse.data as ProviderModelsResponse

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
  }

  useEffect(() => {
    loadSettings()
    loadPrompts()
    if (activeTab === 'general') {
      loadModelsData()
      loadBillingData()
    }
    if (activeTab === 'billing') {
      loadBillingData()
    }
    if (activeTab === 'data-retention') {
      loadRetentionConfig()
    }
    if (activeTab === 'models') {
      loadModelsData()
    }
    if (activeTab === 'api') {
      loadApiProvidersData()
    }
    if (activeTab === 'data-collection') {
      loadCollectionStatus()
      loadRecordsPreview()
    }
  }, [activeTab])

  const loadRetentionConfig = async () => {
    setLoadingRetention(true)
    try {
      const response = await billingAPI.getRetention()
      setRetentionConfig(response.data)
      setRetentionDays(response.data.retention_days)
    } catch (error) {
      appLogger.error({ event: 'retention_config_load_failed', message: 'Failed to load retention config', module: 'settings' })
    } finally {
      setLoadingRetention(false)
    }
  }

  const handleSaveRetention = async () => {
    setSaving(true)
    try {
      const response = await billingAPI.updateRetention({
        retention_days: retentionDays,
        cleanup: cleanupOld
      })
      showNotification({ type: 'success', text: `保存成功${cleanupOld && response.data.deleted_records > 0 ? `，已删除${response.data.deleted_records}条过期记录` : ''}` })
      loadRetentionConfig()
      setCleanupOld(false)
    } catch (error) {
      showNotification({ type: 'error', text: '保存失败' })
    } finally {
      setSaving(false)
    }
  }

  const loadSettings = () => {
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
  }

  const loadPrompts = async () => {
    try {
      const response = await promptsAPI.getActive()
      if (response.data && response.data.content) {
        setSettings(prev => ({ ...prev, promptContent: response.data.content }))
      }
    } catch (error) {
      appLogger.error({ event: 'prompts_load_failed', message: 'Failed to load prompts', module: 'settings' })
    }
  }

  const loadCollectionStatus = async () => {
    try {
      const response = await conversationAPI.getCollectionStatus()
      setCollectionEnabled(Boolean(response.data.enabled))
      setCollectionStats(response.data.stats || null)
    } catch (error) {
      showNotification({ type: 'error', text: '加载收集状态失败' })
    }
  }

  const loadRecordsPreview = async () => {
    setLoadingRecordsPreview(true)
    try {
      const response = await conversationAPI.getRecordsPreview(20)
      setRecordsPreview(response.data.records || [])
    } catch (error) {
      showNotification({ type: 'error', text: '加载最近记录失败' })
    } finally {
      setLoadingRecordsPreview(false)
    }
  }

  const handleToggleCollection = async (enabled: boolean) => {
    setUpdatingCollection(true)
    try {
      await conversationAPI.updateCollectionStatus(enabled)
      setCollectionEnabled(enabled)
      await loadCollectionStatus()
      showNotification({ type: 'success', text: enabled ? '已开启数据收集' : '已关闭数据收集' })
    } catch (error) {
      showNotification({ type: 'error', text: '更新收集开关失败' })
    } finally {
      setUpdatingCollection(false)
    }
  }

  const handleExportRecords = async () => {
    setExportingRecords(true)
    try {
      const params: { start_time?: string; end_time?: string } = {}
      if (exportStartTime) {
        params.start_time = new Date(exportStartTime).toISOString()
      }
      if (exportEndTime) {
        params.end_time = new Date(exportEndTime).toISOString()
      }

      const response = await conversationAPI.exportRecords(params)
      const dispositionHeader = response.headers['content-disposition'] as string | undefined
      const matched = dispositionHeader?.match(/filename="?([^"]+)"?/) || null
      const filename = matched?.[1] || 'conversation_records.jsonl'

      const blob = new Blob([response.data], { type: 'application/x-ndjson' })
      const downloadUrl = window.URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = downloadUrl
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(downloadUrl)

      showNotification({ type: 'success', text: '导出完成' })
    } catch (error) {
      showNotification({ type: 'error', text: '导出失败' })
    } finally {
      setExportingRecords(false)
    }
  }

  const handleCleanupRecords = async () => {
    if (!confirm(`确认清理 ${cleanupDays} 天前的记录吗？`)) return

    setCleaningRecords(true)
    try {
      const response = await conversationAPI.cleanupRecords(cleanupDays)
      const deleted = response.data?.deleted_count ?? 0
      showNotification({ type: 'success', text: `清理完成：已删除 ${deleted} 条记录` })
      await loadRecordsPreview()
      await loadCollectionStatus()
    } catch (error) {
      showNotification({ type: 'error', text: '清理失败' })
    } finally {
      setCleaningRecords(false)
    }
  }

  function loadBillingData() {
    setLoadingModels(true)
    billingAPI.getModels()
      .then(modelsRes => {
        setModels(modelsRes.data.models || [])
      })
      .catch(() => {
        appLogger.error({ event: 'billing_data_load_failed', message: 'Failed to load billing data', module: 'settings' })
      })
      .finally(() => {
        setLoadingModels(false)
      })
  }

  const loadModelsData = async () => {
    setLoadingConfigs(true)
    try {
      const [configsRes, providersRes] = await Promise.all([
        modelsAPI.getConfigurations(),
        modelsAPI.getProviders()
      ])
      const configs: ModelConfiguration[] = configsRes.data.configurations || []
      setConfigurations(configs)
      setProviders(providersRes.data.providers || [])

      // Auto-select default model or first model
      const nextConfigModelOptions = configs.flatMap((configuration) => {
        const candidateModels = configuration.selected_models && configuration.selected_models.length > 0
          ? configuration.selected_models
          : [configuration.model]

        return candidateModels.map((modelName) => ({
          key: `${configuration.id}:${modelName}`,
          configId: configuration.id,
        }))
      })

      const hasSelectedOption = nextConfigModelOptions.some((option) => option.key === selectedConfigModelOptionKey)
      if (nextConfigModelOptions.length > 0 && !hasSelectedOption) {
        const defaultConfig = configs.find((config) => config.is_default) || configs[0]
        const defaultModelName = defaultConfig.selected_models?.[0] || defaultConfig.model
        await handleSelectModelConfig(`${defaultConfig.id}:${defaultModelName}`, configs, true)
      }

      // Sync global selected model if it's empty
      if (!globalSelectedModel && configs.length > 0) {
        const defaultConfig = configs.find((config) => config.is_default) || configs[0]
        const defaultModelName = defaultConfig.selected_models?.[0] || defaultConfig.model
        setGlobalSelectedModel(`${defaultConfig.provider}:${defaultModelName}`)
      }
    } catch (error) {
      appLogger.error({ event: 'models_data_load_failed', message: 'Failed to load models data', module: 'settings' })
    } finally {
      setLoadingConfigs(false)
    }
  }

  const handleSelectModelConfig = async (optionKey: string, configsList?: ModelConfiguration[], skipGlobalSync: boolean = false) => {
    setSelectedConfigModelOptionKey(optionKey)
    const [configIdText, modelName] = optionKey.split(':')
    const configId = Number(configIdText)
    const configs = configsList || configurations
    const config = configs.find(c => c.id === configId)

    if (!skipGlobalSync && config && modelName) {
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
      // Fallback to config values
      setModelCapabilities(null)
      setEditingTemperature(config?.temperature ?? 0.7)
      setEditingTopK(config?.top_k ?? 0.9)
      setEditingMaxTokensLimit(config?.max_tokens_limit ?? '')
    }
  }

  const handleSaveModelParams = async () => {
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
    } catch {
      showNotification({ type: 'error', text: '模型参数保存失败' })
    } finally {
      setSavingModelParams(false)
    }
  }

  const handleResetModelParams = async () => {
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
    } catch {
      showNotification({ type: 'error', text: '重置失败' })
    } finally {
      setSavingModelParams(false)
    }
  }

  // ── 模型独立配置卡片辅助函数 ────────────────────────────────────

  /**
   * 切换模型配置卡片的展开/折叠状态，展开时自动获取模型能力和默认参数。
   * 手风琴模式：展开一个时自动折叠其他已展开的。
   */
  const toggleModelConfig = async (modelName: string) => {
    const configKey = `${providerForm.provider}:${modelName}`

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
        c => c.provider === providerForm.provider && c.model === modelName
      )
      if (!config) {
        loadingCapsRef.current.delete(modelName)
        return
      }

      let caps: ModelCapabilitiesResponse | undefined
      try {
        const capRes = await modelsAPI.getCapabilities(config.id)
        caps = capRes.data
      } catch {
        // 降级：直接使用配置中的值（caps 为 undefined）
      } finally {
        loadingCapsRef.current.delete(modelName)
      }

      setModelEditParams(prev => ({
        ...prev,
        [modelName]: buildModelEditParams(config, caps),
      }))
    }
  }

  /** 更新某个模型的编辑参数 */
  const updateModelEditParam = (modelName: string, field: keyof ModelEditParams, value: number) => {
    setModelEditParams(prev => ({
      ...prev,
      [modelName]: { ...prev[modelName], [field]: value },
    }))
  }

  /** 保存单个模型配置 */
  const handleSaveModelConfig = async (modelName: string) => {
    const params = modelEditParams[modelName]
    if (!params) return

    const config = configurations.find(
      c => c.provider === providerForm.provider && c.model === modelName
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
  }

  /** 重置单个模型配置为默认值 */
  const handleResetModelConfig = async (modelName: string) => {
    const config = configurations.find(
      c => c.provider === providerForm.provider && c.model === modelName
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
  }

  // normalizeProviderBaseUrl 已从 SettingsPage.utils 导入

  const loadApiProvidersData = async (preferredProviderId?: string) => {
    setLoadingApiProviders(true)
    setProviderModelsError(null)
    try {
      const providersRes = await modelsAPI.getProviders()
      const providerList: ModelProvider[] = providersRes.data.providers || []
      const validProviders = providerList.filter(item =>
        (item.configuration_count || 0) > 0 || item.has_api_key || item.api_endpoint
      )
      setProviders(validProviders)

      if (validProviders.length === 0) {
        setSelectedProviderId('')
        setProviderModels([])
        setProviderForm({
          config_id: null,
          provider: '',
          display_name: '',
          icon: '',
          api_endpoint: '',
          api_key: '',
          has_api_key: false,
          selected_models: []
        })
        return
      }

      const preferred = preferredProviderId || selectedProviderId
      const nextProviderId = preferred && validProviders.some(item => item.id === preferred)
        ? preferred
        : validProviders[0].id

      await loadProviderDetail(nextProviderId)
    } catch (error) {
      showNotification({ type: 'error', text: '加载供应商列表失败' })
    } finally {
      setLoadingApiProviders(false)
    }
  }

  const loadProviderDetail = async (providerId: string) => {
    if (!providerId) return

    setLoadingProviderDetail(true)
    setProviderModelsError(null)

    try {
      const detailRes = await modelsAPI.getProviderDetail(providerId)
      const detailData = detailRes.data as ProviderDetailResponse
      const config = detailData.configuration
      const providerData = detailData.provider

      const selectedModels = Array.isArray(config.selected_models)
        ? config.selected_models
        : (providerData.selected_models || [])

      const api_endpoint = (config.base_url || config.api_endpoint || (config as unknown as Record<string, unknown>).api_url || providerData.base_url || providerData.api_endpoint || (providerData as unknown as Record<string, unknown>).api_url || '') as string
      
      setProviderForm({
        config_id: config.id,
        provider: config.provider || providerId,
        display_name: config.display_name || providerData.display_name || providerData.name || providerId,
        icon: config.icon || providerData.icon || '',
        api_endpoint,
        api_key: '',
        has_api_key: Boolean(config.has_api_key ?? providerData.has_api_key),
        selected_models: selectedModels
      })
      setSelectedProviderId(providerId)

      await fetchProviderModels(providerId, selectedModels, false, { api_endpoint })
    } catch (error) {
      showNotification({ type: 'error', text: '加载供应商详情失败' })
    } finally {
      setLoadingProviderDetail(false)
    }
  }

  const fetchProviderModels = async (
    providerId: string, 
    fallbackSelectedModels: string[] = [], 
    openModal: boolean = true,
    credentials?: { api_endpoint?: string; api_key?: string }
  ) => {
    if (!providerId) return

    setLoadingProviderModels(true)
    invalidateRemoteModelCache(providerId)

    try {
      setProviderModelsError(null)
      const response = await modelsAPI.getModelsByProvider(providerId, credentials)
      const data = response.data as ProviderModelsResponse
      const selectedModels = Array.isArray(data.selected_models)
        ? data.selected_models
        : fallbackSelectedModels

      const models = data.models || []
      setFetchedRemoteModels(models)
      
      // Update provider form's selected_models so the main page displays them
      setProviderForm(prev => ({ ...prev, selected_models: selectedModels }))

      if (!data.success) {
        setProviderModelsError(data.error?.message || '获取模型列表失败')
        return // 获取失败时，不再打开弹窗或覆盖 models
      }

      if (openModal) {
        // Open the modal with pre-selected models
        setModalSelectedModels(selectedModels)
        setShowImportModal(true)
      }
    } catch (error) {
      setFetchedRemoteModels([])
      setProviderModelsError('获取模型列表失败')
    } finally {
      setLoadingProviderModels(false)
    }
  }

  const handleImportModels = async () => {
    if (!providerForm.config_id || !providerForm.provider) {
      showNotification({ type: 'error', text: '当前供应商配置不完整' })
      return
    }

    if (providerForm.api_endpoint) {
      try {
        new URL(providerForm.api_endpoint)
      } catch (error) {
        showNotification({ type: 'error', text: 'API URL 格式不正确，请输入包含 http:// 或 https:// 的完整链接' })
        return
      }
    }

    setImporting(true)
    try {
      const newSelected = [...modalSelectedModels]
      const normalizedBaseUrl = normalizeProviderBaseUrl(providerForm.provider, providerForm.api_endpoint)
      const nextApiKey = providerApiKeyInputRef.current?.value.trim() || ''

      // 1. 保存 Provider 凭据到独立表
      const credPayload: { display_name?: string; icon?: string; api_endpoint?: string; api_key?: string } = {
        display_name: providerForm.display_name.trim() || undefined,
        icon: providerForm.icon.trim() || undefined,
        api_endpoint: normalizedBaseUrl || undefined,
      }
      if (nextApiKey) {
        credPayload.api_key = nextApiKey
      }
      await modelsAPI.saveProviderCredential(providerForm.provider, credPayload)

      // 2. 更新 selected_models（如果有已有配置则更新）
      if (providerForm.config_id) {
        await modelsAPI.updateProviderSelectedModels(providerForm.provider, {
          selected_models: newSelected
        })
      }

      setProviderForm(prev => ({
        ...prev,
        selected_models: newSelected,
        api_endpoint: normalizedBaseUrl
      }))

      if (providerApiKeyInputRef.current) {
        providerApiKeyInputRef.current.value = ''
      }

      invalidateRemoteModelCache(providerForm.provider)
      showNotification({ type: 'success', text: '模型导入及配置保存成功' })
      setShowImportModal(false)

      // 3. 为每个新导入的模型创建独立的配置记录（后端自动关联 credential_id）
      const existingModelNames = new Set(
        configurations
          .filter(c => c.provider === providerForm.provider)
          .map(c => c.model)
      )
      const modelsToCreate = newSelected.filter(m => !existingModelNames.has(m))
      if (modelsToCreate.length > 0) {
        // 依次创建，避免并发时的唯一约束冲突
        for (const modelName of modelsToCreate) {
          try {
            await modelsAPI.createConfiguration({
              provider: providerForm.provider,
              model: modelName,
              display_name: modelName,
              is_default: false
            })
          } catch (e) {
            // 409 冲突表示已存在，静默跳过
            const status = (e as any)?.response?.status
            if (status !== 409) {
              appLogger.error({ event: 'imported_model_config_create_failed', module: 'settings', message: `Failed to create config for model: ${modelName}`, extra: { model: modelName } })
            }
          }
        }
        if (modelsToCreate.length > 0) {
          showNotification({ type: 'success', text: `已为 ${modelsToCreate.length} 个模型创建独立配置` })
        }
      }

      await Promise.all([
        loadModelsData(), // Refresh AI parameters options
        loadApiProvidersData(providerForm.provider) // Refresh provider details to ensure UI sync
      ])
    } catch (error) {
      showNotification({ type: 'error', text: `模型导入失败：${getApiErrorDetail(error)}` })
    } finally {
      setImporting(false)
    }
  }

  const handleBatchDeleteModels = async () => {
    if (!providerForm.config_id || !providerForm.provider) return
    setDeletingModels(true)
    try {
      const newSelected = providerForm.selected_models.filter(m => !selectedForDeletion.includes(m))
      const normalizedBaseUrl = normalizeProviderBaseUrl(providerForm.provider, providerForm.api_endpoint)
      const nextApiKey = providerApiKeyInputRef.current?.value.trim() || ''
      const updatePayload: {
        display_name?: string
        icon?: string
        api_endpoint?: string
        api_key?: string
        selected_models?: string[]
      } = {
        display_name: providerForm.display_name.trim() || undefined,
        icon: providerForm.icon.trim() || undefined,
        api_endpoint: normalizedBaseUrl || undefined,
        selected_models: newSelected
      }

      if (nextApiKey) {
        updatePayload.api_key = nextApiKey
      }

      await modelsAPI.updateConfiguration(providerForm.config_id, updatePayload)
      
      setProviderForm(prev => ({ 
        ...prev, 
        selected_models: newSelected,
        api_endpoint: normalizedBaseUrl
      }))
      
      if (providerApiKeyInputRef.current) {
        providerApiKeyInputRef.current.value = ''
      }

      invalidateRemoteModelCache(providerForm.provider)
      setSelectedForDeletion([])
      showNotification({ type: 'success', text: '批量删除及配置保存成功' })
      setShowDeleteModelsModal(false)
      
      await Promise.all([
        loadModelsData(), // Refresh AI parameters options
        loadApiProvidersData(providerForm.provider) // Refresh provider details to ensure UI sync
      ])
    } catch (error) {
      showNotification({ type: 'error', text: `批量删除失败：${getApiErrorDetail(error)}` })
    } finally {
      setDeletingModels(false)
    }
  }

  const handleOpenCreateProviderModal = () => {
    setAddProviderForm(createInitialAddProviderForm())
    setShowCreateProviderModal(true)
  }

  // 发现本地 Ollama 可用模型
  const handleDiscoverOllamaModels = async () => {
    setLoadingOllama(true)
    setOllamaError(null)
    try {
      const response = await modelsAPI.discoverOllamaModels()
      const data = response.data
      setOllamaModels(data.models || [])
      if (data.count === 0) {
        setOllamaError('未发现 Ollama 模型，请确认 Ollama 服务已启动且已拉取模型')
      }
    } catch {
      setOllamaError('无法连接 Ollama 服务，请确认服务已启动')
      setOllamaModels([])
    } finally {
      setLoadingOllama(false)
    }
  }

  // 获取所有提供商连接状态
  const handleCheckProviderStatuses = async () => {
    setLoadingProviderStatuses(true)
    try {
      const response = await modelsAPI.getProvidersStatus()
      setProviderStatuses(response.data.providers || [])
    } catch {
      showNotification({ type: 'error', text: '获取提供商状态失败' })
    } finally {
      setLoadingProviderStatuses(false)
    }
  }

  const handleCloseCreateProviderModal = () => {
    if (creatingProvider) return
    setShowCreateProviderModal(false)
  }

  useEffect(() => {
    if (!showCreateProviderModal) return

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        handleCloseCreateProviderModal()
      }
    }

    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [showCreateProviderModal, creatingProvider])

  useEffect(() => {
    if (!showDeleteConfirmModal) return

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        handleCloseDeleteConfirmModal()
      }
    }

    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [showDeleteConfirmModal, deletingProvider])

  const handleCreateProvider = async () => {
    const providerId = normalizeProviderId(addProviderForm.provider)
    const nextDisplayName = addProviderForm.display_name.trim()

    if (!providerId) {
      showNotification({ type: 'error', text: '请输入供应商标识' })
      return
    }

    if (addProviderForm.api_endpoint) {
      try {
        new URL(addProviderForm.api_endpoint)
      } catch (error) {
        showNotification({ type: 'error', text: 'API URL 格式不正确，请输入包含 http:// 或 https:// 的完整链接' })
        return
      }
    }

    setCreatingProvider(true)

    try {
      const normalizedBaseUrl = normalizeProviderBaseUrl(providerId, addProviderForm.api_endpoint)
      await modelsAPI.saveProviderCredential(providerId, {
        display_name: nextDisplayName || undefined,
        api_endpoint: normalizedBaseUrl || undefined,
      })

      setAddProviderForm(createInitialAddProviderForm())
      setShowCreateProviderModal(false)
      invalidateRemoteModelCache(providerId)
      showNotification({ type: 'success', text: '供应商创建成功' })
      await loadApiProvidersData(providerId)
    } catch (error) {
      showNotification({ type: 'error', text: `供应商创建失败：${getApiErrorDetail(error)}` })
    } finally {
      setCreatingProvider(false)
    }
  }

  const handleSaveProviderConfig = async () => {
    if (!providerForm.config_id || !providerForm.provider) {
      showNotification({ type: 'error', text: '当前供应商配置不完整' })
      return
    }

    if (providerForm.api_endpoint) {
      try {
        new URL(providerForm.api_endpoint)
      } catch (error) {
        showNotification({ type: 'error', text: 'API URL 格式不正确，请输入包含 http:// 或 https:// 的完整链接' })
        return
      }
    }

    setSaving(true)

    try {
      const normalizedBaseUrl = normalizeProviderBaseUrl(providerForm.provider, providerForm.api_endpoint)
      const nextApiKey = providerApiKeyInputRef.current?.value.trim() || ''

      const credPayload: {
        display_name?: string
        icon?: string
        api_endpoint?: string
        api_key?: string
      } = {
        display_name: providerForm.display_name.trim() || undefined,
        icon: providerForm.icon.trim() || undefined,
        api_endpoint: normalizedBaseUrl || undefined,
      }
      if (nextApiKey) {
        credPayload.api_key = nextApiKey
      }

      setProviderForm(prev => ({ ...prev, api_endpoint: normalizedBaseUrl }))
      await modelsAPI.saveProviderCredential(providerForm.provider, credPayload)
      if (providerForm.config_id) {
        await modelsAPI.updateProviderSelectedModels(providerForm.provider, {
          selected_models: providerForm.selected_models
        })
      }

      // 保存成功后清空 API 密钥输入框，避免明文长期留存在前端状态中
      if (providerApiKeyInputRef.current) {
        providerApiKeyInputRef.current.value = ''
      }
      invalidateRemoteModelCache(providerForm.provider)
      showNotification({ type: 'success', text: '供应商配置保存成功' })
      await loadApiProvidersData(providerForm.provider)
    } catch (error) {
      showNotification({ type: 'error', text: `保存供应商配置失败：${getApiErrorDetail(error)}` })
    } finally {
      setSaving(false)
    }
  }

  const handleOpenDeleteConfirmModal = () => {
    if (!providerForm.provider) {
      showNotification({ type: 'error', text: '当前供应商配置不完整' })
      return
    }
    setShowDeleteConfirmModal(true)
  }

  const handleCloseDeleteConfirmModal = () => {
    if (deletingProvider) return
    setShowDeleteConfirmModal(false)
  }

  const confirmDeleteProvider = async () => {
    if (!providerForm.provider) return

    setDeletingProvider(true)

    try {
      await modelsAPI.deleteProvider(providerForm.provider)
      invalidateRemoteModelCache(providerForm.provider)
      showNotification({ type: 'success', text: '供应商删除成功' })
      setShowDeleteConfirmModal(false)
      // 清除已删除厂商的配置引用，防止后续操作指向无效配置
      setProviderForm(prev => ({ ...prev, config_id: null }))
      await loadApiProvidersData()
    } catch (error) {
      showNotification({ type: 'error', text: '供应商删除失败' })
    } finally {
      setDeletingProvider(false)
    }
  }

  const handleProviderChange = async (provider: string) => {
    setNewConfig(prev => ({ ...prev, provider, model: '' }))
    if (provider) {
      try {
        const response = await modelsAPI.getModelsByProvider(provider)
        setProviderModels(response.data.models || [])
      } catch (error) {
        appLogger.error({ event: 'provider_models_load_failed', message: 'Failed to load provider models', module: 'settings' })
      }
    } else {
      setProviderModels([])
    }
  }

  const handleAddConfiguration = async () => {
    if (!newConfig.provider || !newConfig.model) {
      showNotification({ type: 'error', text: '请选择提供商和模型' })
      return
    }

    try {
      await modelsAPI.createConfiguration({
        provider: newConfig.provider,
        model: newConfig.model,
        display_name: newConfig.display_name || undefined,
        description: newConfig.description || undefined,
        is_default: newConfig.is_default,
      })
      showNotification({ type: 'success', text: '添加成功' })
      setNewConfig({ provider: '', model: '', display_name: '', description: '', is_default: false })
      setShowAddForm(false)
      invalidateRemoteModelCache(newConfig.provider)
      loadModelsData()
    } catch (error) {
      showNotification({ type: 'error', text: '添加失败' })
    }
  }

  const handleDeleteConfiguration = async (configId: number) => {
    if (!confirm('确定要删除这个模型配置吗？')) return

    try {
      await modelsAPI.deleteConfiguration(configId)
      showNotification({ type: 'success', text: '删除成功' })
      loadModelsData()
    } catch (error) {
      showNotification({ type: 'error', text: '删除失败' })
    }
  }

  const handleSetDefault = async (configId: number) => {
    try {
      await modelsAPI.setDefaultConfiguration(configId)
      showNotification({ type: 'success', text: '设置成功' })

      const config = configurations.find(c => c.id === configId)
      if (config) {
        const defaultModelName = config.selected_models?.[0] || config.model
        setGlobalSelectedModel(`${config.provider}:${defaultModelName}`)
      }

      loadModelsData()
    } catch (error) {
      showNotification({ type: 'error', text: '设置失败' })
    }
  }

  const handleEditConfig = (config: ModelConfiguration) => {
    setEditingConfigId(config.id)
    setEditConfigForm({
      display_name: config.display_name || '',
      description: config.description || '',
      input_modality: config.input_modality?.length ? [...config.input_modality] : ['text'],
      output_modality: config.output_modality?.length ? [...config.output_modality] : ['text'],
    })
  }

  const toggleModality = (direction: 'input' | 'output', modalityType: string) => {
    setEditConfigForm(prev => {
      const key = direction === 'input' ? 'input_modality' : 'output_modality'
      const current = prev[key]
      if (current.includes(modalityType)) {
        // 至少保留一个模态
        if (current.length <= 1) {
          showNotification({ type: 'error', text: '至少需要保留一个模态类型' })
          return prev
        }
        return { ...prev, [key]: current.filter(m => m !== modalityType) }
      }
      return { ...prev, [key]: [...current, modalityType] }
    })
  }

  const handleSaveConfigEdit = async () => {
    if (!editingConfigId) return
    setSavingConfigEdit(true)
    try {
      await modelsAPI.updateConfiguration(editingConfigId, {
        display_name: editConfigForm.display_name || undefined,
        description: editConfigForm.description || undefined,
        input_modality: JSON.stringify(editConfigForm.input_modality),
        output_modality: JSON.stringify(editConfigForm.output_modality),
      })
      showNotification({ type: 'success', text: '模型信息保存成功' })
      setEditingConfigId(null)
      loadModelsData()
    } catch {
      showNotification({ type: 'error', text: '保存失败' })
    } finally {
      setSavingConfigEdit(false)
    }
  }

  const saveSettings = async () => {
    setSaving(true)

    try {
      safeSetJsonItem('app_settings', buildPersistedSettings(settings))

      // 同步偏好到服务端，实现跨浏览器持久化
      userAPI.updatePreferences({
        theme: settings.theme,
        language: settings.language,
        apiProvider: settings.apiProvider,
        requireConfirm: settings.requireConfirm,
        enableAudit: settings.enableAudit,
        maxToolCallRounds: settings.maxToolCallRounds,
      }).catch(() => {
        // 静默失败，localStorage 已保存
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
      showNotification({ type: 'error', text: '保存失败，请重试' })
    } finally {
      setSaving(false)
    }
  }

  const handleChange = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    setSettings(prev => ({ ...prev, [key]: value }))
  }

  const handleEditModel = (model: ModelPricing) => {
    setEditingModel(model.id)
    setEditPrices({
      input_price: model.input_price.toString(),
      output_price: model.output_price.toString()
    })
  }

  const handleSaveModelPrice = async (modelId: number) => {
    try {
      await billingAPI.updateModelPricing(modelId, {
        input_price: parseFloat(editPrices.input_price),
        output_price: parseFloat(editPrices.output_price)
      })
      setEditingModel(null)
      loadBillingData()
      showNotification({ type: 'success', text: '价格更新成功' })
    } catch (error) {
      showNotification({ type: 'error', text: '价格更新失败' })
    }
  }

  // groupedModels and remaining functions

  const groupedModels = models.reduce((acc, model) => {
    if (!acc[model.provider]) {
      acc[model.provider] = []
    }
    acc[model.provider].push(model)
    return acc
  }, {} as Record<string, ModelPricing[]>)

  const renderSecondarySidebar = () => {
    const tabs = [
      { id: 'general', label: '通用设置', icon: <SettingsIcon size={18} /> },
      { id: 'api', label: 'API配置', icon: <Plug size={18} /> },
      { id: 'prompts', label: '提示词', icon: <Cpu size={18} /> },
      { id: 'billing', label: '计费配置', icon: <Briefcase size={18} /> },
      { id: 'models', label: '模型管理', icon: <Cpu size={18} /> },
      { id: 'data-retention', label: '数据保留', icon: <HardDrive size={18} /> },
      { id: 'data-collection', label: '数据采集', icon: <HardDrive size={18} /> },
      { id: 'security', label: '安全审计', icon: <ShieldAlert size={18} /> },
      { id: 'mcp', label: 'MCP配置', icon: <SettingsIcon size={18} /> },
      { id: 'permissions', label: '权限管理', icon: <Key size={18} /> },
      { id: 'env-vars', label: '环境变量', icon: <Sliders size={18} /> },
    ]

    return (
      <div className={styles['secondary-nav']}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            className={`${styles['nav-item']} ${activeTab === tab.id ? styles['active'] : ''}`}
            onClick={() => handleTabChange(tab.id)}
          >
            {tab.icon}
            <span>{tab.label}</span>
          </button>
        ))}
      </div>
    )
  }

  return (
    <PageLayout 
      title="设置" 
      secondarySidebar={renderSecondarySidebar()}
      className={styles['settings-page']}
    >
      <div className={styles['settings-content']}>
        {message && (
          <div className={`${styles['message']} ${styles[message.type] || message.type}`}>
            {message.text}
          </div>
        )}

        {activeTab === 'general' && (
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
          />
        )}

        {activeTab === 'api' && (
          <ApiSettings
            loadingApiProviders={loadingApiProviders}
            loadingProviderDetail={loadingProviderDetail}
            loadingProviderModels={loadingProviderModels}
            providerModelsError={providerModelsError}
            providers={providers}
            selectedProviderId={selectedProviderId}
            providerForm={providerForm}
            providerApiKeyInputRef={providerApiKeyInputRef}
            providerStatuses={providerStatuses}
            loadingProviderStatuses={loadingProviderStatuses}
            ollamaModels={ollamaModels}
            loadingOllama={loadingOllama}
            ollamaError={ollamaError}
            saving={saving}
            deletingProvider={deletingProvider}
            configurations={configurations}
            expandedModelConfigs={expandedModelConfigs}
            modelEditParams={modelEditParams}
            savingModelConfig={savingModelConfig}
            selectedForDeletion={selectedForDeletion}
            onOpenCreateProviderModal={handleOpenCreateProviderModal}
            onProviderFormChange={setProviderForm}
            onLoadProviderDetail={loadProviderDetail}
            onSaveProviderConfig={handleSaveProviderConfig}
            onOpenDeleteConfirmModal={handleOpenDeleteConfirmModal}
            onFetchModels={fetchProviderModels}
            onDiscoverOllama={handleDiscoverOllamaModels}
            onCheckProviderStatuses={handleCheckProviderStatuses}
            onToggleModelConfig={toggleModelConfig}
            onSaveModelConfig={handleSaveModelConfig}
            onResetModelConfig={handleResetModelConfig}
            onUpdateModelEditParam={updateModelEditParam}
            onSelectionChange={(modelName, checked) => {
              if (checked) {
                setSelectedForDeletion(prev => [...prev, modelName])
              } else {
                setSelectedForDeletion(prev => prev.filter(m => m !== modelName))
              }
            }}
            onOpenDeleteModelsModal={() => setShowDeleteModelsModal(true)}
          />
        )}

        {activeTab === 'prompts' && (
          <PromptsTab
            promptContent={settings.promptContent}
            saving={saving}
            onPromptChange={(value) => handleChange('promptContent', value)}
            onSave={saveSettings}
          />
        )}

        {activeTab === 'billing' && (
          <BillingTab
            loadingModels={loadingModels}
            models={models}
            editingModel={editingModel}
            editPrices={editPrices}
            groupedModels={groupedModels}
            onEditModel={handleEditModel}
            onInputPriceChange={(value) => setEditPrices(prev => ({ ...prev, input_price: value }))}
            onOutputPriceChange={(value) => setEditPrices(prev => ({ ...prev, output_price: value }))}
            onSaveModelPrice={handleSaveModelPrice}
            onCancelEdit={() => setEditingModel(null)}
          />
        )}

        {activeTab === 'models' && (
          <ModelsTab
            showAddForm={showAddForm}
            configurations={configurations}
            loading={loadingConfigs}
            providers={providers}
            providerModels={providerModels}
            selectedOption={selectedConfigModelOption}
            editingConfigId={editingConfigId}
            editConfigForm={editConfigForm}
            savingEdit={savingConfigEdit}
            providerNameMap={providerNameMap}
            newConfig={newConfig}
            onToggleAddForm={() => setShowAddForm(!showAddForm)}
            onProviderChange={handleProviderChange}
            onModelChange={(model) => setNewConfig(prev => ({ ...prev, model }))}
            onFieldChange={(field, value) => setNewConfig(prev => ({ ...prev, [field]: value }))}
            onAddConfiguration={handleAddConfiguration}
            onEditConfig={handleEditConfig}
            onSaveConfigEdit={handleSaveConfigEdit}
            onCancelEdit={() => setEditingConfigId(null)}
            onEditFormChange={(field, value) => setEditConfigForm(prev => ({ ...prev, [field]: value }))}
            onToggleModality={toggleModality}
            onDeleteConfiguration={handleDeleteConfiguration}
            onSetDefault={handleSetDefault}
          />
        )}
        {activeTab === 'data-collection' && (
          <DataCollectionTab
            collectionEnabled={collectionEnabled}
            collectionStats={collectionStats}
            updatingCollection={updatingCollection}
            recordsPreview={recordsPreview}
            loadingRecordsPreview={loadingRecordsPreview}
            exportStartTime={exportStartTime}
            exportEndTime={exportEndTime}
            exportingRecords={exportingRecords}
            cleanupDays={cleanupDays}
            cleaningRecords={cleaningRecords}
            onToggleCollection={handleToggleCollection}
            onLoadRecordsPreview={loadRecordsPreview}
            onExportRecords={handleExportRecords}
            onCleanupRecords={handleCleanupRecords}
            onExportStartTimeChange={setExportStartTime}
            onExportEndTimeChange={setExportEndTime}
            onCleanupDaysChange={setCleanupDays}
          />
        )}

        {activeTab === 'data-retention' && (
          <DataRetentionTab
            loadingRetention={loadingRetention}
            retentionConfig={retentionConfig}
            retentionDays={retentionDays}
            cleanupOld={cleanupOld}
            saving={saving}
            onLoadRetentionConfig={loadRetentionConfig}
            onSaveRetention={handleSaveRetention}
            onRetentionDaysChange={setRetentionDays}
            onCleanupOldChange={setCleanupOld}
          />
        )}

        {activeTab === 'security' && (
          <div className={styles['settings-section']}>
            <h2>安全审计</h2>
            <Suspense fallback={<TabLoadingFallback />}>
              <SecuritySettings />
            </Suspense>
          </div>
        )}

        {activeTab === 'mcp' && (
          <div className={styles['settings-section']}>
            <Suspense fallback={<TabLoadingFallback />}>
              <MCPSettings />
            </Suspense>
          </div>
        )}

        {activeTab === 'permissions' && (
          <div className={styles['settings-section']}>
            <Suspense fallback={<TabLoadingFallback />}>
              <PermissionSettings />
            </Suspense>
          </div>
        )}

        {activeTab === 'env-vars' && (
          <div className={styles['settings-section']}>
            <Suspense fallback={<TabLoadingFallback />}>
              <EnvVarSettings />
            </Suspense>
          </div>
        )}

        <CreateProviderModal
          isOpen={showCreateProviderModal}
          addProviderForm={addProviderForm}
          creatingProvider={creatingProvider}
          onClose={handleCloseCreateProviderModal}
          onChangeForm={setAddProviderForm}
          onCreate={handleCreateProvider}
        />

        <DeleteConfirmModal
          isOpen={showDeleteConfirmModal}
          providerName={providerForm.display_name.trim() || providerForm.provider}
          deletingProvider={deletingProvider}
          onClose={handleCloseDeleteConfirmModal}
          onConfirm={confirmDeleteProvider}
        />

        <ImportModelsModal
          isOpen={showImportModal}
          fetchedRemoteModels={fetchedRemoteModels}
          modalSelectedModels={modalSelectedModels}
          importing={importing}
          onClose={() => setShowImportModal(false)}
          onToggleModel={(modelName, checked) => {
            if (checked) {
              setModalSelectedModels(prev => [...prev, modelName])
            } else {
              setModalSelectedModels(prev => prev.filter(m => m !== modelName))
            }
          }}
          onImport={handleImportModels}
        />

        <DeleteModelsModal
          isOpen={showDeleteModelsModal}
          selectedCount={selectedForDeletion.length}
          deletingModels={deletingModels}
          onClose={() => setShowDeleteModelsModal(false)}
          onConfirm={handleBatchDeleteModels}
        />
      </div>
    </PageLayout>
  )
}

export default SettingsPage
