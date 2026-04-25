import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { 
  Settings as SettingsIcon, 
  ShieldAlert, 
  Cpu, 
  Briefcase, 
  Plug, 
  HardDrive
} from 'lucide-react'
import PageLayout from '@/shared/components/PageLayout/PageLayout'
import { promptsAPI, conversationAPI, ConversationRecordItem, ConversationCollectionStatusResponse } from '@/shared/api/api'
import { billingAPI, ModelPricing, RetentionConfig } from '@/features/billing/billingApi'
import { modelsAPI, ModelConfiguration, ModelProvider, ProviderDetailResponse, ProviderModel, ProviderModelsResponse, ModelCapabilitiesResponse, OllamaModel, ProviderConnectionStatus } from '@/features/settings/modelsApi'
import { useChatStore } from '@/features/chat/store/chatStore'
import { useNotification } from '@/shared/hooks/useNotification'
import { appLogger } from '@/shared/utils/logger'
import { safeGetJsonItem, safeSetJsonItem } from '@/shared/utils/safeStorage'
import MCPSettings from './MCPSettings'
import SecuritySettings from './SecuritySettings'
import styles from './SettingsPage.module.css'

interface Settings {
  theme: string
  language: string
  apiProvider: string
  apiKey: string
  promptContent: string
  requireConfirm: boolean
  enableAudit: boolean
}

type PersistedSettings = Pick<Settings, 'theme' | 'language' | 'apiProvider' | 'requireConfirm' | 'enableAudit'>

function isPersistedSettings(value: unknown): value is Partial<PersistedSettings> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false
  }

  const candidate = value as Record<string, unknown>
  return (
    (candidate.theme === undefined || typeof candidate.theme === 'string') &&
    (candidate.language === undefined || typeof candidate.language === 'string') &&
    (candidate.apiProvider === undefined || typeof candidate.apiProvider === 'string') &&
    (candidate.requireConfirm === undefined || typeof candidate.requireConfirm === 'boolean') &&
    (candidate.enableAudit === undefined || typeof candidate.enableAudit === 'boolean')
  )
}

function buildPersistedSettings(settings: Settings): PersistedSettings {
  return {
    theme: settings.theme,
    language: settings.language,
    apiProvider: settings.apiProvider,
    requireConfirm: settings.requireConfirm,
    enableAudit: settings.enableAudit,
  }
}

interface ApiProviderFormState {
  config_id: number | null
  provider: string
  display_name: string
  icon: string
  api_endpoint: string
  api_key: string
  has_api_key: boolean
  selected_models: string[]
  max_tokens: number | ''
}

function SettingsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const queryParams = new URLSearchParams(location.search)
  const initialTab = queryParams.get('tab') || 'general'

  const createInitialAddProviderForm = () => ({
    provider: '',
    display_name: '',
    icon: '',
    api_endpoint: '',
    api_key: '',
    base_model: '',
    max_tokens: '' as number | ''
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

  // Model parameter panel state
  const [selectedModelConfigId, setSelectedModelConfigId] = useState<number | null>(null)
  const [modelCapabilities, setModelCapabilities] = useState<ModelCapabilitiesResponse | null>(null)
  const [editingTemperature, setEditingTemperature] = useState(0.7)
  const [editingTopK, setEditingTopK] = useState(0.9)
  const [editingMaxTokens, setEditingMaxTokens] = useState<number | null>(null)
  const [savingModelParams, setSavingModelParams] = useState(false)

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
  const addProviderApiKeyInputRef = useRef<HTMLInputElement | null>(null)

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
    selected_models: [],
    max_tokens: ''
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

  // 加载可用模型列表（供通用设置页模型选择器使用）
  const loadGlobalModelOptions = async () => {
    setModelLoading(true)
    setModelError(null)
    try {
      const response = await modelsAPI.getProviders()
      const providersList = response.data.providers || []
      const flatConfigs: { id: string; provider: string; model: string; display_name: string }[] = []
      providersList.forEach((provider: { id: string; selected_models?: string[]; display_name?: string; name?: string }) => {
        const selected = provider.selected_models || []
        selected.forEach((modelName: string) => {
          flatConfigs.push({
            id: `${provider.id}:${modelName}`,
            provider: provider.id,
            model: modelName,
            display_name: `${provider.display_name || provider.name || provider.id} - ${modelName}`
          })
        })
      })
      setModelOptions(flatConfigs)
      // 如果当前没有选中模型或选中的模型不存在，自动选择第一个
      if (flatConfigs.length > 0) {
        const exists = flatConfigs.some(c => c.id === globalSelectedModel)
        if (!globalSelectedModel || !exists) {
          setGlobalSelectedModel(flatConfigs[0].id)
        }
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
    } finally {
      setModelLoading(false)
    }
  }

  useEffect(() => {
    loadSettings()
    loadPrompts()
    if (activeTab === 'general') {
      loadGlobalModelOptions()
      loadModelsData()
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
      setSettings((prev) => ({ ...prev, ...savedSettings }))
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

  const loadBillingData = async () => {
    setLoadingModels(true)
    try {
      const [modelsRes] = await Promise.all([
        billingAPI.getModels()
      ])
      setModels(modelsRes.data.models || [])
    } catch (error) {
      appLogger.error({ event: 'billing_data_load_failed', message: 'Failed to load billing data', module: 'settings' })
    } finally {
      setLoadingModels(false)
    }
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
      if (configs.length > 0 && !selectedModelConfigId) {
        const defaultConfig = configs.find(c => c.is_default) || configs[0]
        await handleSelectModelConfig(defaultConfig.id, configs)
      }
    } catch (error) {
      appLogger.error({ event: 'models_data_load_failed', message: 'Failed to load models data', module: 'settings' })
    } finally {
      setLoadingConfigs(false)
    }
  }

  const handleSelectModelConfig = async (configId: number, configsList?: ModelConfiguration[]) => {
    setSelectedModelConfigId(configId)
    const configs = configsList || configurations
    const config = configs.find(c => c.id === configId)

    try {
      const capRes = await modelsAPI.getCapabilities(configId)
      setModelCapabilities(capRes.data)
      setEditingTemperature(config?.temperature ?? capRes.data.defaults.temperature)
      setEditingTopK(config?.top_k ?? capRes.data.defaults.top_k)
      setEditingMaxTokens(config?.max_tokens_limit ?? null)
    } catch {
      // Fallback to config values
      setModelCapabilities(null)
      setEditingTemperature(config?.temperature ?? 0.7)
      setEditingTopK(config?.top_k ?? 0.9)
      setEditingMaxTokens(config?.max_tokens_limit ?? null)
    }
  }

  const handleSaveModelParams = async () => {
    if (!selectedModelConfigId) return
    setSavingModelParams(true)
    try {
      await modelsAPI.updateParameters(selectedModelConfigId, {
        temperature: editingTemperature,
        top_k: editingTopK,
        max_tokens_limit: editingMaxTokens,
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
    if (!selectedModelConfigId) return
    setSavingModelParams(true)
    try {
      const res = await modelsAPI.resetParameters(selectedModelConfigId)
      const config = res.data.configuration
      setEditingTemperature(config?.temperature ?? 0.7)
      setEditingTopK(config?.top_k ?? 0.9)
      setEditingMaxTokens(config?.max_tokens_limit ?? null)
      showNotification({ type: 'success', text: '已重置为默认参数' })
      await loadModelsData()
    } catch {
      showNotification({ type: 'error', text: '重置失败' })
    } finally {
      setSavingModelParams(false)
    }
  }

  const formatTokenCount = (tokens: number | null | undefined): string => {
    if (tokens == null) return '-'
    if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`
    if (tokens >= 1000) return `${(tokens / 1000).toFixed(0)}K`
    return String(tokens)
  }


  const normalizeProviderId = (value: string) => value.trim().toLowerCase().replace(/\s+/g, '-')

  const normalizeProviderBaseUrl = (apiEndpoint: string) => {
    let raw = apiEndpoint.trim()
    if (!raw) {
      return ''
    }

    try {
      new URL(raw)
    } catch (e) {
      // Return raw if invalid URL, let backend or other logic handle, or maybe we can just proceed
    }

    const knownSuffixes = [
      '/v1/chat/completions',
      '/compatible-mode/v1/chat/completions',
      '/api/paas/v4/chat/completions',
      '/v1/messages',
      '/v1beta/models',
      '/v1/models',
      '/chat/completions',
      '/models'
    ]

    let trimmed = raw.replace(/\/+$/, '')
    const lowerTrimmed = trimmed.toLowerCase()
    
    for (const suffix of knownSuffixes) {
      if (lowerTrimmed.endsWith(suffix.toLowerCase())) {
        trimmed = trimmed.slice(0, trimmed.length - suffix.length).replace(/\/+$/, '')
        break
      }
    }

    if (!trimmed.toLowerCase().endsWith('/v1')) {
      trimmed = `${trimmed}/v1`
    }

    return trimmed
  }

  const loadApiProvidersData = async (preferredProviderId?: string) => {
    setLoadingApiProviders(true)
    setProviderModelsError(null)
    try {
      const providersRes = await modelsAPI.getProviders()
      const providerList: ModelProvider[] = providersRes.data.providers || []
      setProviders(providerList)

      if (providerList.length === 0) {
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
          selected_models: [],
          max_tokens: ''
        })
        return
      }

      const validProviders = providerList.filter(item => (item.configuration_count || 0) > 0)
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
          selected_models: [],
          max_tokens: ''
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

      setProviderForm({
        config_id: config.id,
        provider: config.provider || providerId,
        display_name: config.display_name || providerData.display_name || providerData.name || providerId,
        icon: config.icon || providerData.icon || '',
        api_endpoint: (config.base_url || config.api_endpoint || (config as unknown as Record<string, unknown>).api_url || providerData.base_url || providerData.api_endpoint || (providerData as unknown as Record<string, unknown>).api_url || '') as string,
        api_key: '',
        has_api_key: Boolean(config.has_api_key ?? providerData.has_api_key),
        selected_models: selectedModels,
        max_tokens: config.max_tokens ?? ''
      })
      setSelectedProviderId(providerId)

      await fetchProviderModels(providerId, selectedModels, false)
    } catch (error) {
      showNotification({ type: 'error', text: '加载供应商详情失败' })
    } finally {
      setLoadingProviderDetail(false)
    }
  }

  const fetchProviderModels = async (providerId: string, fallbackSelectedModels: string[] = [], openModal: boolean = true) => {
    if (!providerId) return

    setLoadingProviderModels(true)

    try {
      setProviderModelsError(null)
      const response = await modelsAPI.getModelsByProvider(providerId)
      const data = response.data as ProviderModelsResponse
      const selectedModels = Array.isArray(data.selected_models)
        ? data.selected_models
        : fallbackSelectedModels

      const models = data.models || []
      setFetchedRemoteModels(models)
      
      // Update provider form's selected_models so the main page displays them
      setProviderForm(prev => ({ ...prev, selected_models: selectedModels }))

      if (openModal) {
        // Open the modal with pre-selected models
        setModalSelectedModels(selectedModels)
        setShowImportModal(true)
      }

      if (!data.success && data.error?.message) {
        setProviderModelsError(data.error.message)
      }
    } catch (error) {
      setFetchedRemoteModels([])
      setProviderModelsError('获取模型列表失败')
    } finally {
      setLoadingProviderModels(false)
    }
  }

  const handleImportModels = async () => {
    if (!providerForm.provider) return
    setImporting(true)
    try {
      const newSelected = [...modalSelectedModels]
      await modelsAPI.updateProviderSelectedModels(providerForm.provider, { selected_models: newSelected })
      setProviderForm(prev => ({ ...prev, selected_models: newSelected }))
      showNotification({ type: 'success', text: '模型导入成功' })
      setShowImportModal(false)
    } catch (error) {
      showNotification({ type: 'error', text: '模型导入失败' })
    } finally {
      setImporting(false)
    }
  }

  const handleBatchDeleteModels = async () => {
    if (!providerForm.provider) return
    setDeletingModels(true)
    try {
      const newSelected = providerForm.selected_models.filter(m => !selectedForDeletion.includes(m))
      await modelsAPI.updateProviderSelectedModels(providerForm.provider, { selected_models: newSelected })
      setProviderForm(prev => ({ ...prev, selected_models: newSelected }))
      setSelectedForDeletion([])
      showNotification({ type: 'success', text: '批量删除成功' })
      setShowDeleteModelsModal(false)
    } catch (error) {
      showNotification({ type: 'error', text: '批量删除失败' })
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

  // 格式化文件大小
  const formatModelSize = (bytes: number): string => {
    if (!bytes) return '-'
    if (bytes >= 1073741824) return `${(bytes / 1073741824).toFixed(1)} GB`
    if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(0)} MB`
    return `${(bytes / 1024).toFixed(0)} KB`
  }

  // 获取连接状态的显示样式
  const getStatusIndicator = (status: string): { label: string; color: string } => {
    switch (status) {
      case 'connected': return { label: '已连接', color: '#22c55e' }
      case 'auth_error': return { label: '认证失败', color: '#ef4444' }
      case 'timeout': return { label: '超时', color: '#f59e0b' }
      case 'unreachable': return { label: '不可达', color: '#ef4444' }
      case 'unconfigured': return { label: '未配置', color: '#9ca3af' }
      default: return { label: '异常', color: '#ef4444' }
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
    const baseModel = addProviderForm.base_model.trim() || 'custom-model'
    const nextApiKey = addProviderApiKeyInputRef.current?.value.trim() || ''

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
      const normalizedBaseUrl = normalizeProviderBaseUrl(addProviderForm.api_endpoint)
      await modelsAPI.createConfiguration({
        provider: providerId,
        model: baseModel,
        display_name: addProviderForm.display_name.trim() || providerId,
        icon: addProviderForm.icon.trim() || undefined,
        api_endpoint: normalizedBaseUrl || undefined,
        api_key: nextApiKey || undefined,
        selected_models: [],
        max_tokens: addProviderForm.max_tokens === '' ? null : Number(addProviderForm.max_tokens),
        is_default: false
      })

      if (addProviderApiKeyInputRef.current) {
        addProviderApiKeyInputRef.current.value = ''
      }
      setAddProviderForm(createInitialAddProviderForm())
      setShowCreateProviderModal(false)
      showNotification({ type: 'success', text: '供应商创建成功' })
      await loadApiProvidersData(providerId)
    } catch (error) {
      showNotification({ type: 'error', text: '供应商创建失败' })
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
      const normalizedBaseUrl = normalizeProviderBaseUrl(providerForm.api_endpoint)
      const nextApiKey = providerApiKeyInputRef.current?.value.trim() || ''
      const updatePayload: {
        display_name?: string
        icon?: string
        api_endpoint?: string
        api_key?: string
        selected_models?: string[]
        max_tokens?: number | null
      } = {
        display_name: providerForm.display_name.trim() || undefined,
        icon: providerForm.icon.trim() || undefined,
        api_endpoint: normalizedBaseUrl || undefined,
        selected_models: providerForm.selected_models,
        max_tokens: providerForm.max_tokens === '' ? null : Number(providerForm.max_tokens)
      }

      if (nextApiKey) {
        updatePayload.api_key = nextApiKey
      }

      setProviderForm(prev => ({ ...prev, api_endpoint: normalizedBaseUrl }))
      await modelsAPI.updateConfiguration(providerForm.config_id, updatePayload)
      await modelsAPI.updateProviderSelectedModels(providerForm.provider, {
        selected_models: providerForm.selected_models
      })

      // 保存成功后清空 API 密钥输入框，避免明文长期留存在前端状态中
      if (providerApiKeyInputRef.current) {
        providerApiKeyInputRef.current.value = ''
      }
      showNotification({ type: 'success', text: '供应商配置保存成功' })
      await loadApiProvidersData(providerForm.provider)
    } catch (error) {
      showNotification({ type: 'error', text: '保存供应商配置失败' })
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
      showNotification({ type: 'success', text: '供应商删除成功' })
      setShowDeleteConfirmModal(false)
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
      loadModelsData()
    } catch (error) {
      showNotification({ type: 'error', text: '设置失败' })
    }
  }

  const saveSettings = async () => {
    setSaving(true)

    try {
      safeSetJsonItem('app_settings', buildPersistedSettings(settings))
      
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

  const handleChange = (key: keyof Settings, value: string | boolean) => {
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

  const formatPrice = (price: number, currency: string) => {
    const symbol = currency === 'CNY' ? '¥' : '$'
    return `${symbol}${price.toFixed(4)}`
  }

  const groupedModels = models.reduce((acc, model) => {
    if (!acc[model.provider]) {
      acc[model.provider] = []
    }
    acc[model.provider].push(model)
    return acc
  }, {} as Record<string, ModelPricing[]>)

  const _getProviderName = (providerId: string) => {
    const provider = providers.find(p => p.id === providerId)
    return provider ? provider.name : providerId
  }
  void _getProviderName

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
          <div className={styles['settings-section']}>
            <h2>通用设置</h2>
            <div className={styles['setting-item']}>
              <label>主题</label>
              <select
                value={settings.theme}
                onChange={(e) => handleChange('theme', e.target.value)}
              >
                <option value="light">浅色</option>
                <option value="dark">深色</option>
              </select>
            </div>
            <div className={styles['setting-item']}>
              <label>语言</label>
              <select
                value={settings.language}
                onChange={(e) => handleChange('language', e.target.value)}
              >
                <option value="zh">中文</option>
                <option value="en">English</option>
              </select>
            </div>
            <button
              className={`btn btn-primary`}
              onClick={saveSettings}
              disabled={saving}
            >
              {saving ? '保存中...' : '保存设置'}
            </button>

            <h2 style={{ marginTop: '32px' }}>主模型选择</h2>
            <p className={styles['section-desc']}>选择聊天页面使用的默认AI模型和输出模式，对全局生效。</p>
            <div className={styles['setting-item']}>
              <label>输出模式</label>
              <select
                value={outputMode}
                onChange={(e) => {
                  setOutputMode(e.target.value as 'stream' | 'direct')
                  appLogger.info({ event: 'global_output_mode_change', module: 'settings', action: 'change_output_mode', status: 'success', message: 'output mode changed', extra: { mode: e.target.value } })
                }}
              >
                <option value="stream">流式传输</option>
                <option value="direct">直接输出</option>
              </select>
            </div>
            <div className={styles['setting-item']}>
              <label>默认模型</label>
              {modelLoading ? (
                <span style={{ color: 'var(--color-text-tertiary)', fontSize: '13px' }}>加载模型中...</span>
              ) : modelError ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{ color: 'var(--color-danger)', fontSize: '13px' }}>{modelError}</span>
                  <button className="btn btn-sm" onClick={loadGlobalModelOptions}>重试</button>
                </div>
              ) : modelOptions.length === 0 ? (
                <span style={{ color: 'var(--color-text-tertiary)', fontSize: '13px' }}>暂无可用模型，请先在 API 配置中添加供应商和模型</span>
              ) : (
                <select
                  value={globalSelectedModel}
                  onChange={(e) => {
                    setGlobalSelectedModel(e.target.value)
                    appLogger.info({ event: 'global_model_change', module: 'settings', action: 'change_default_model', status: 'success', message: 'default model changed', extra: { model: e.target.value } })
                    showNotification({ type: 'success', text: '默认模型已更新' })
                  }}
                >
                  {modelOptions.map((opt) => (
                    <option key={opt.id} value={opt.id}>{opt.display_name}</option>
                  ))}
                </select>
              )}
            </div>

            {/* AI参数配置 - 从模型管理移入通用设置 */}
            {configurations.length > 0 && (
              <div className={styles['model-param-panel']} style={{ marginTop: '24px' }}>
                <h3>AI参数配置</h3>
                <p className={styles['section-desc']}>为选定模型调整生成参数，影响输出风格和长度。</p>
                <div className={styles['model-param-grid']}>
                  <div className={styles['form-group']}>
                    <label>配置模型</label>
                    <select
                      value={selectedModelConfigId ?? ''}
                      onChange={(e) => {
                        const id = Number(e.target.value)
                        if (id) handleSelectModelConfig(id)
                      }}
                    >
                      <option value="">选择模型</option>
                      {configurations.map(c => {
                        const displayProvider = providerNameMap[c.provider] || c.provider
                        const models = c.selected_models && c.selected_models.length > 0 ? c.selected_models : [c.model]
                        return models.map(modelName => (
                          <option key={`${c.id}:${modelName}`} value={c.id}>
                            {displayProvider} / {modelName}
                          </option>
                        ))
                      })}
                    </select>
                  </div>

                  <div className={styles['form-group']}>
                    <label>
                      温度 (Temperature): {editingTemperature.toFixed(1)}
                    </label>
                    <div className={styles['slider-row']}>
                      <input
                        type="range"
                        min={0}
                        max={2}
                        step={0.1}
                        value={editingTemperature}
                        onChange={(e) => setEditingTemperature(parseFloat(e.target.value))}
                        disabled={!selectedModelConfigId || modelCapabilities?.capabilities.supports_temperature === false}
                        className={styles['param-slider']}
                      />
                      <input
                        type="number"
                        min={0}
                        max={2}
                        step={0.1}
                        value={editingTemperature}
                        onChange={(e) => {
                          const val = parseFloat(e.target.value)
                          if (!isNaN(val) && val >= 0 && val <= 2) setEditingTemperature(val)
                        }}
                        disabled={!selectedModelConfigId || modelCapabilities?.capabilities.supports_temperature === false}
                        className={styles['param-number-input']}
                      />
                    </div>
                    {modelCapabilities?.capabilities.supports_temperature === false && (
                      <span className={styles['param-hint']}>该模型不支持温度调节</span>
                    )}
                  </div>

                  <div className={styles['form-group']}>
                    <label>Top K / Top P</label>
                    <input
                      type="number"
                      min={0}
                      max={1}
                      step={0.1}
                      value={editingTopK}
                      onChange={(e) => {
                        const val = parseFloat(e.target.value)
                        if (!isNaN(val) && val >= 0 && val <= 1) setEditingTopK(val)
                      }}
                      disabled={!selectedModelConfigId || modelCapabilities?.capabilities.supports_top_k === false}
                      className={styles['param-number-input']}
                    />
                    {modelCapabilities?.capabilities.supports_top_k === false && (
                      <span className={styles['param-hint']}>该模型不支持 Top K / Top P 调节</span>
                    )}
                  </div>

                  <div className={styles['form-group']}>
                    <label>
                      最大 Tokens
                      {modelCapabilities && (
                        <span className={styles['param-hint-inline']}>
                          {' '}(上限: {formatTokenCount(modelCapabilities.limits.max_tokens_max)})
                        </span>
                      )}
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={modelCapabilities?.limits.max_tokens_max ?? 999999}
                      value={editingMaxTokens ?? modelCapabilities?.defaults.max_tokens ?? ''}
                      onChange={(e) => {
                        const val = e.target.value === '' ? null : parseInt(e.target.value)
                        setEditingMaxTokens(val)
                      }}
                      disabled={!selectedModelConfigId}
                      placeholder={modelCapabilities ? `默认: ${formatTokenCount(modelCapabilities.defaults.max_tokens)}` : ''}
                    />
                  </div>
                </div>

                <div className={styles['model-param-actions']}>
                  <button
                    className={`btn btn-primary`}
                    onClick={handleSaveModelParams}
                    disabled={!selectedModelConfigId || savingModelParams}
                  >
                    {savingModelParams ? '保存中...' : '保存参数'}
                  </button>
                  <button
                    className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                    onClick={handleResetModelParams}
                    disabled={!selectedModelConfigId || savingModelParams}
                  >
                    重置为默认
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'api' && (
          <div className={styles['settings-section']}>
            <div className={styles['section-header']}>
              <h2>API配置</h2>
              <button
                className={`btn btn-primary`}
                onClick={handleOpenCreateProviderModal}
              >
                新增供应商
              </button>
            </div>
            <p className={styles['section-desc']}>左侧管理供应商，右侧配置基础 URL、API Key，并从远端获取模型后用复选框选择。</p>

            <div className={styles['api-config-layout']}>
              <aside className={styles['provider-sidebar']}>
                {loadingApiProviders ? (
                  <div className={styles['loading']}>加载供应商中...</div>
                ) : providers.length === 0 ? (
                  <div className={styles['empty-state']}>
                    <p>暂无供应商配置</p>
                    <p className={styles['hint']}>请先添加供应商</p>
                  </div>
                ) : (
                  <div className={styles['provider-list']}>
                    {providers.map(provider => {
                      const isActive = provider.id === selectedProviderId
                      const displayName = provider.display_name || provider.name || provider.id
                      return (
                        <button
                          key={provider.id}
                          className={`${styles['provider-item']} ${isActive ? styles['active'] : ''}`}
                          onClick={() => {
                            if ((provider.configuration_count || 0) === 0) {
                              showNotification({ type: 'error', text: '该供应商暂无可用配置，请先新增供应商配置' })
                              return
                            }
                            loadProviderDetail(provider.id)
                          }}
                        >
                          <span className={styles['provider-avatar']}>
                            {provider.icon ? (
                              <img src={provider.icon} alt={displayName} />
                            ) : (
                              <span>{displayName.slice(0, 1).toUpperCase()}</span>
                            )}
                          </span>
                          <span className={styles['provider-item-content']}>
                            <span className={styles['provider-item-title']}>{displayName}</span>
                            <span className={styles['provider-item-sub']}>{provider.id}</span>
                            {(provider.configuration_count || 0) === 0 && (
                              <span className={styles['provider-item-empty']}>未配置</span>
                            )}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                )}
              </aside>

              <section className={styles['provider-detail-panel']}>
                {loadingProviderDetail ? (
                  <div className={styles['loading']}>加载供应商详情中...</div>
                ) : !selectedProviderId ? (
                  <div className={styles['empty-state']}>
                    <p>请选择左侧供应商</p>
                  </div>
                ) : (
                  <>
                    <div className={styles['form-row']}>
                      <div className={styles['form-group']}>
                        <label>供应商标识</label>
                        <input type="text" value={providerForm.provider} disabled />
                      </div>
                      <div className={styles['form-group']}>
                        <label>显示名称</label>
                        <input
                          type="text"
                          value={providerForm.display_name}
                          onChange={(e) => setProviderForm(prev => ({ ...prev, display_name: e.target.value }))}
                          placeholder="供应商显示名称"
                        />
                      </div>
                    </div>

                    <div className={styles['form-row']}>
                      <div className={styles['form-group']}>
                        <label>图标地址（可选）</label>
                        <input
                          type="text"
                          value={providerForm.icon}
                          onChange={(e) => setProviderForm(prev => ({ ...prev, icon: e.target.value }))}
                          placeholder="https://example.com/icon.png"
                        />
                      </div>
                      <div className={styles['form-group']}>
                        <label>基础 URL</label>
                        <input
                          type="text"
                          value={providerForm.api_endpoint}
                          onChange={(e) => setProviderForm(prev => ({ ...prev, api_endpoint: e.target.value }))}
                          placeholder="https://api.example.com"
                        />
                      </div>
                    </div>

                    <div className={styles['form-row']}>
                      <div className={styles['form-group']}>
                        <label>API Key</label>
                        <input
                          key={`provider-api-key-${providerForm.config_id ?? providerForm.provider}`}
                          type="password"
                          ref={providerApiKeyInputRef}
                          defaultValue=""
                          autoComplete="new-password"
                          placeholder={providerForm.has_api_key ? '已配置密钥，留空表示不修改' : '输入供应商 API Key'}
                        />
                      </div>
                      <div className={styles['form-group']}>
                        <label>最大 Token 数 (可选)</label>
                        <input
                          type="number"
                          value={providerForm.max_tokens}
                          onChange={(e) => setProviderForm(prev => ({ ...prev, max_tokens: e.target.value === '' ? '' : Number(e.target.value) }))}
                          placeholder="例如 4096"
                          min="1"
                        />
                      </div>
                    </div>

                    <div className={styles['provider-detail-actions']}>
                      <button
                        type="button"
                        className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                        onClick={() => fetchProviderModels(providerForm.provider, providerForm.selected_models, true)}
                        disabled={loadingProviderModels || deletingProvider}
                      >
                        {loadingProviderModels ? '获取中...' : '获取模型列表'}
                      </button>
                      <button
                        className={`btn btn-primary`}
                        onClick={handleSaveProviderConfig}
                        disabled={saving || deletingProvider}
                      >
                        {saving ? '保存中...' : '保存供应商配置'}
                      </button>
                      <button
                        className={`btn ${styles['btn-danger'] || 'btn-danger'}`}
                        onClick={handleOpenDeleteConfirmModal}
                        disabled={deletingProvider}
                      >
                        {deletingProvider ? '删除中...' : '删除供应商'}
                      </button>
                    </div>
                    {providerModelsError && (
                      <div className={`${styles['message']} ${styles['error']}`} style={{ marginTop: '12px' }}>{providerModelsError}</div>
                    )}

                    <div className={styles['provider-models-section']}>
                      <div className={styles['provider-models-header']} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                        <h3 style={{ margin: 0 }}>已导入模型</h3>
                        {selectedForDeletion.length > 0 && (
                          <button
                            className={`btn ${styles['btn-danger'] || 'btn-danger'}`}
                            onClick={() => setShowDeleteModelsModal(true)}
                          >
                            批量删除 ({selectedForDeletion.length})
                          </button>
                        )}
                      </div>
                      
                      {providerForm.selected_models.length === 0 ? (
                        <div className={styles['empty-state']}>
                          <p>暂无已导入模型，请点击上方“获取模型列表”进行选择和导入</p>
                        </div>
                      ) : (
                        <div className={styles['provider-model-list']}>
                          {providerForm.selected_models.map(modelName => {
                            const checked = selectedForDeletion.includes(modelName)
                            return (
                              <label key={modelName} className={styles['provider-model-item']}>
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={(e) => {
                                    if (e.target.checked) {
                                      setSelectedForDeletion(prev => [...prev, modelName])
                                    } else {
                                      setSelectedForDeletion(prev => prev.filter(m => m !== modelName))
                                    }
                                  }}
                                />
                                <span className={styles['provider-model-name']}>{modelName}</span>
                              </label>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  </>
                )}
              </section>
            </div>

            {/* 提供商连接状态 */}
            <div style={{ marginTop: '24px', padding: '16px', border: '1px solid #e5e7eb', borderRadius: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <h3 style={{ margin: 0 }}>提供商连接状态</h3>
                <button
                  className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                  onClick={handleCheckProviderStatuses}
                  disabled={loadingProviderStatuses}
                >
                  {loadingProviderStatuses ? '检测中...' : '检测连接状态'}
                </button>
              </div>
              {providerStatuses.length > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '8px' }}>
                  {providerStatuses.map(ps => {
                    const indicator = getStatusIndicator(ps.status)
                    return (
                      <div key={ps.provider} style={{ padding: '8px 12px', border: '1px solid #e5e7eb', borderRadius: '6px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: indicator.color, flexShrink: 0 }} />
                        <span style={{ fontWeight: 500 }}>{ps.display_name || ps.provider}</span>
                        <span style={{ color: '#6b7280', fontSize: '12px', marginLeft: 'auto' }}>{indicator.label}</span>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>

            {/* Ollama 本地模型发现 */}
            <div style={{ marginTop: '24px', padding: '16px', border: '1px solid #e5e7eb', borderRadius: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <h3 style={{ margin: 0 }}>Ollama 本地模型</h3>
                <button
                  className={`btn btn-primary`}
                  onClick={handleDiscoverOllamaModels}
                  disabled={loadingOllama}
                >
                  {loadingOllama ? '发现中...' : '发现本地模型'}
                </button>
              </div>
              <p style={{ color: '#6b7280', fontSize: '13px', marginBottom: '12px' }}>
                自动发现本地 Ollama 服务中已拉取的模型，需先启动 Ollama 服务
              </p>
              {ollamaError && (
                <div className={`${styles['message']} ${styles['error']}`} style={{ marginBottom: '12px' }}>{ollamaError}</div>
              )}
              {ollamaModels.length > 0 && (
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid #e5e7eb' }}>
                      <th style={{ textAlign: 'left', padding: '8px', fontWeight: 500 }}>模型名称</th>
                      <th style={{ textAlign: 'left', padding: '8px', fontWeight: 500 }}>大小</th>
                      <th style={{ textAlign: 'left', padding: '8px', fontWeight: 500 }}>更新时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ollamaModels.map(model => (
                      <tr key={model.name} style={{ borderBottom: '1px solid #f3f4f6' }}>
                        <td style={{ padding: '8px', fontFamily: 'monospace' }}>{model.name}</td>
                        <td style={{ padding: '8px', color: '#6b7280' }}>{formatModelSize(model.size)}</td>
                        <td style={{ padding: '8px', color: '#6b7280' }}>{model.modified_at ? new Date(model.modified_at).toLocaleString('zh-CN') : '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        )}

        {activeTab === 'prompts' && (
          <div className={styles['settings-section']}>
            <h2>提示词配置</h2>
            <p className={styles['section-desc']}>
              自定义AI助手的行为和角色提示词
            </p>
            <textarea
              className={styles['prompt-editor']}
              value={settings.promptContent}
              onChange={(e) => handleChange('promptContent', e.target.value)}
              placeholder="输入系统提示词..."
              rows={12}
            />
            <div className={styles['prompt-helper']}>
              <p>支持的变量：{'{user_name}'} - 用户名，{'{current_time}'} - 当前时间</p>
            </div>
            <button
              className={`btn btn-primary`}
              onClick={saveSettings}
              disabled={saving}
            >
              {saving ? '保存中...' : '保存提示词'}
            </button>
          </div>
        )}

        {activeTab === 'billing' && (
          <div className={styles['settings-section']}>
            <h2>模型价格配置</h2>
            <p className={styles['section-desc']}>
              配置各AI厂商的模型API价格（单位：百万tokens）
            </p>
            
            {loadingModels ? (
              <div className={styles['loading']}>加载中...</div>
            ) : (
              <div className={styles['pricing-table-container']}>
                {Object.entries(groupedModels).map(([provider, providerModels]) => (
                  <div key={provider} className={styles['pricing-provider-group']}>
                    <h3 className={styles['provider-title']}>{provider.toUpperCase()}</h3>
                    <table className={styles['pricing-table']}>
                      <thead>
                        <tr>
                          <th>模型</th>
                          <th>输入价格</th>
                          <th>输出价格</th>
                          <th>缓存价格</th>
                          <th>上下文窗口</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {providerModels.map((model) => (
                          <tr key={model.id}>
                            <td className={styles['model-name']}>{model.model}</td>
                            <td>
                              {editingModel === model.id ? (
                                <input
                                  type="number"
                                  value={editPrices.input_price}
                                  onChange={(e) => setEditPrices(prev => ({ ...prev, input_price: e.target.value }))}
                                  className={styles['price-input']}
                                  step="0.0001"
                                />
                              ) : (
                                formatPrice(model.input_price, model.currency)
                              )}
                            </td>
                            <td>
                              {editingModel === model.id ? (
                                <input
                                  type="number"
                                  value={editPrices.output_price}
                                  onChange={(e) => setEditPrices(prev => ({ ...prev, output_price: e.target.value }))}
                                  className={styles['price-input']}
                                  step="0.0001"
                                />
                              ) : (
                                formatPrice(model.output_price, model.currency)
                              )}
                            </td>
                            <td>
                              {model.cache_hit_price 
                                ? formatPrice(model.cache_hit_price, model.currency)
                                : '-'
                              }
                            </td>
                            <td>
                              {model.context_window 
                                ? `${(model.context_window / 1000).toFixed(0)}K`
                                : '-'
                              }
                            </td>
                            <td>
                              {editingModel === model.id ? (
                                <div className={styles['action-buttons']}>
                                  <button 
                                    className={`btn ${styles['btn-small'] || 'btn-small'} btn-primary`}
                                    onClick={() => handleSaveModelPrice(model.id)}
                                  >
                                    保存
                                  </button>
                                  <button 
                                    className={`btn ${styles['btn-small'] || 'btn-small'}`}
                                    onClick={() => setEditingModel(null)}
                                  >
                                    取消
                                  </button>
                                </div>
                              ) : (
                                <button 
                                  className={`btn ${styles['btn-small'] || 'btn-small'}`}
                                  onClick={() => handleEditModel(model)}
                                >
                                  编辑
                                </button>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {activeTab === 'models' && (
          <div className={styles['settings-section']}>
            <div className={styles['section-header']}>
              <h2>模型管理</h2>
              <button 
                className={`btn btn-primary`}
                onClick={() => setShowAddForm(!showAddForm)}
              >
                {showAddForm ? '取消' : '+ 添加模型'}
              </button>
            </div>
            <p className={styles['section-desc']}>
              配置可用的AI模型参数，设置的默认模型将自动在聊天页面选中
            </p>

            {showAddForm && (
              <div className={styles['add-config-form']}>
                <div className={styles['form-row']}>
                  <div className={styles['form-group']}>
                    <label>提供商</label>
                    <select
                      value={newConfig.provider}
                      onChange={(e) => handleProviderChange(e.target.value)}
                    >
                      <option value="">选择提供商</option>
                      {providers.map(p => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className={styles['form-group']}>
                    <label>模型</label>
                    <select
                      value={newConfig.model}
                      onChange={(e) => setNewConfig(prev => ({ ...prev, model: e.target.value }))}
                      disabled={!newConfig.provider}
                    >
                      <option value="">选择模型</option>
                      {providerModels.map(m => (
                        <option key={m.id} value={m.model}>{m.model}</option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className={styles['form-row']}>
                  <div className={styles['form-group']}>
                    <label>显示名称（可选）</label>
                    <input
                      type="text"
                      value={newConfig.display_name}
                      onChange={(e) => setNewConfig(prev => ({ ...prev, display_name: e.target.value }))}
                      placeholder="例如：GPT-4.1"
                    />
                  </div>
                </div>
                <div className={styles['form-row']}>
                  <div className={styles['form-group']}>
                    <label>描述（可选）</label>
                    <input
                      type="text"
                      value={newConfig.description}
                      onChange={(e) => setNewConfig(prev => ({ ...prev, description: e.target.value }))}
                      placeholder="模型描述"
                    />
                  </div>
                </div>
                <div className={styles['form-row']}>
                  <div className={`${styles['form-group']} ${styles['checkbox-group']}`}>
                    <input
                      type="checkbox"
                      id="is-default-new"
                      checked={newConfig.is_default}
                      onChange={(e) => setNewConfig(prev => ({ ...prev, is_default: e.target.checked }))}
                    />
                    <label htmlFor="is-default-new">设为默认模型</label>
                  </div>
                </div>
                <button className={`btn btn-primary`} onClick={handleAddConfiguration}>
                  添加
                </button>
              </div>
            )}

            {/* 模型参数配置已移至通用设置 -> 主模型选择 */}

            {/* Model Management Table */}
            {loadingConfigs ? (
              <div className={styles['loading']}>加载中...</div>
            ) : configurations.length === 0 ? (
              <div className={styles['empty-state']}>
                <p>暂无配置的模型</p>
                <p className={styles['hint']}>点击上方"添加模型"按钮来配置第一个模型</p>
              </div>
            ) : (
              <div className={styles['model-mgmt-table-wrapper']}>
                <h3>模型列表</h3>
                <table className={styles['model-mgmt-table']}>
                  <thead>
                    <tr>
                      <th>图标</th>
                      <th>模型名</th>
                      <th>提供者</th>
                      <th>规格</th>
                      <th>图片</th>
                      <th>多模</th>
                      <th>状态</th>
                      <th>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {configurations.map(config => {
                      const contextWindow = config.model_spec?.context_window
                      return (
                        <tr key={config.id} className={selectedModelConfigId === config.id ? styles['selected-row'] : ''}>
                          <td>
                            <span className={styles['model-icon-badge']}>
                              {config.icon || config.provider.charAt(0).toUpperCase()}
                            </span>
                          </td>
                          <td>
                            <div className={styles['model-name-cell']}>
                              {config.display_name || config.model}
                              {config.is_default && <span className={styles['default-badge']}>默认</span>}
                            </div>
                          </td>
                          <td>{config.provider}</td>
                          <td>{contextWindow ? formatTokenCount(contextWindow) : '-'}</td>
                          <td>{config.supports_vision ? '✅' : '❌'}</td>
                          <td>{config.is_multimodal ? '✅' : '❌'}</td>
                          <td>
                            <span className={`${styles['status-badge']} ${styles[`status-${config.status || 'active'}`]}`}>
                              {config.status || 'active'}
                            </span>
                          </td>
                          <td>
                            <div className={styles['table-actions']}>
                              {!config.is_default && (
                                <button
                                  className={`btn ${styles['btn-small'] || 'btn-small'}`}
                                  onClick={() => handleSetDefault(config.id)}
                                >
                                  设为默认
                                </button>
                              )}
                              <button
                                className={`btn ${styles['btn-small'] || 'btn-small'} ${styles['btn-danger'] || 'btn-danger'}`}
                                onClick={() => handleDeleteConfiguration(config.id)}
                              >
                                删除
                              </button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        {activeTab === 'data-collection' && (
          <div className={styles['settings-section']}>
            <h2>对话数据采集</h2>
            <p className={styles['section-desc']}>
              采集调用链数据，预览最近记录，导出 JSONL，并清理历史数据。
            </p>

            <div className={`${styles['setting-item']} ${styles['checkbox']}`}>
              <input
                type="checkbox"
                id="conversation-collection"
                checked={collectionEnabled}
                onChange={(e) => handleToggleCollection(e.target.checked)}
                disabled={updatingCollection}
              />
              <label htmlFor="conversation-collection">
                {updatingCollection ? '更新中...' : '启用对话数据采集'}
              </label>
            </div>

            {collectionStats && (
              <div className={styles['collection-stats-grid']}>
                <div className={styles['collection-stat-card']}>
                  <span className={styles['collection-stat-label']}>队列占用</span>
                  <span className={styles['collection-stat-value']}>{collectionStats.queue_size} / {collectionStats.queue_maxsize}</span>
                </div>
                <div className={styles['collection-stat-card']}>
                  <span className={styles['collection-stat-label']}>丢弃数量</span>
                  <span className={styles['collection-stat-value']}>{collectionStats.dropped_count}</span>
                </div>
                <div className={styles['collection-stat-card']}>
                  <span className={styles['collection-stat-label']}>跟踪用户数</span>
                  <span className={styles['collection-stat-value']}>{collectionStats.tracked_user_count}</span>
                </div>
              </div>
            )}

            <div className={styles['collection-actions-row']}>
              <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={loadRecordsPreview} disabled={loadingRecordsPreview}>
                {loadingRecordsPreview ? '刷新中...' : '预览最近 20 条'}
              </button>
            </div>

            <div className={styles['collection-export-panel']}>
              <h3>导出 JSONL</h3>
              <div className={styles['form-row']}>
                <div className={styles['form-group']}>
                  <label>开始时间（可选）</label>
                  <input
                    type="datetime-local"
                    value={exportStartTime}
                    onChange={(e) => setExportStartTime(e.target.value)}
                  />
                </div>
                <div className={styles['form-group']}>
                  <label>结束时间（可选）</label>
                  <input
                    type="datetime-local"
                    value={exportEndTime}
                    onChange={(e) => setExportEndTime(e.target.value)}
                  />
                </div>
              </div>
              <button className={`btn btn-primary`} onClick={handleExportRecords} disabled={exportingRecords}>
                {exportingRecords ? '导出中...' : '导出数据集'}
              </button>
            </div>

            <div className={styles['collection-cleanup-panel']}>
              <h3>清理历史数据</h3>
              <div className={styles['form-row']}>
                <div className={styles['form-group']}>
                  <label>删除早于以下天数的记录</label>
                  <input
                    type="number"
                    min={0}
                    max={3650}
                    value={cleanupDays}
                    onChange={(e) => setCleanupDays(parseInt(e.target.value) || 30)}
                  />
                </div>
              </div>
              <button className={`btn ${styles['btn-danger'] || 'btn-danger'}`} onClick={handleCleanupRecords} disabled={cleaningRecords}>
                {cleaningRecords ? '清理中...' : '执行清理'}
              </button>
            </div>

            <div className={styles['collection-preview-panel']}>
              <h3>最近记录</h3>
              {loadingRecordsPreview ? (
                <div className={styles['loading']}>加载中...</div>
              ) : recordsPreview.length === 0 ? (
                <div className={styles['empty-state']}>
                  <p>暂无记录</p>
                </div>
              ) : (
                <div className={styles['collection-record-list']}>
                  {recordsPreview.map((record) => (
                    <div key={record.id} className={styles['collection-record-item']}>
                      <div className={styles['collection-record-row']}>
                        <span className={styles['collection-record-node']}>{record.node_type}</span>
                        <span className={`${styles['collection-record-status']} ${styles[record.status] || record.status}`}>{record.status}</span>
                      </div>
                      <div className={`${styles['collection-record-row']} ${styles['muted']}`}>
                        <span>会话: {record.session_id}</span>
                        <span>{record.timestamp ? new Date(record.timestamp).toLocaleString('zh-CN') : '-'}</span>
                      </div>
                      <div className={`${styles['collection-record-row']} ${styles['muted']}`}>
                        <span>模型: {record.provider || '-'} / {record.model || '-'}</span>
                        <span>耗时: {record.execution_duration_ms ?? '-'} ms</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'data-retention' && (
          <div className={styles['settings-section']}>
            <h2>数据保留设置</h2>
            <p className={styles['section-desc']}>
              配置计费数据的保留天数，超出保留期限的数据将被自动清理
            </p>

            {loadingRetention ? (
              <div className={styles['loading']}>加载中...</div>
            ) : (
              <>
                <div className={styles['setting-item']}>
                  <label>最大保存天数</label>
                  <input
                    type="number"
                    value={retentionDays}
                    onChange={(e) => setRetentionDays(parseInt(e.target.value) || 365)}
                    min={1}
                    max={3650}
                    style={{ width: '150px' }}
                  />
                  <span style={{ marginLeft: '8px', color: 'var(--color-text-secondary)', fontSize: '14px' }}>
                    天（范围：1-3650）
                  </span>
                </div>

                {retentionConfig && (
                  <div className={styles['setting-item']}>
                    <label>当前数据状态</label>
                    <div style={{ fontSize: '14px', color: 'var(--color-text-secondary)', marginTop: '8px' }}>
                      <p>总记录数：{retentionConfig.total_records}</p>
                      <p>
                        数据范围：{retentionConfig.oldest_record
                          ? new Date(retentionConfig.oldest_record).toLocaleDateString('zh-CN')
                          : '无'}
                        {' - '}
                        {retentionConfig.newest_record
                          ? new Date(retentionConfig.newest_record).toLocaleDateString('zh-CN')
                          : '无'}
                      </p>
                    </div>
                  </div>
                )}

                <div className={`${styles['setting-item']} ${styles['checkbox']}`}>
                  <input
                    type="checkbox"
                    id="cleanup-old"
                    checked={cleanupOld}
                    onChange={(e) => setCleanupOld(e.target.checked)}
                  />
                  <label htmlFor="cleanup-old">
                    保存后清理超出保留期限的旧数据
                  </label>
                </div>

                <button
                  className={`btn btn-primary`}
                  onClick={handleSaveRetention}
                  disabled={saving}
                >
                  {saving ? '保存中...' : '保存设置'}
                </button>
              </>
            )}
          </div>
        )}

        {activeTab === 'security' && (
          <div className={styles['settings-section']}>
            <h2>安全审计</h2>
            <SecuritySettings />
          </div>
        )}

        {activeTab === 'mcp' && (
          <div className={styles['settings-section']}>
            <MCPSettings />
          </div>
        )}

        {showCreateProviderModal && (
          <div className={styles['provider-modal-overlay']} onClick={handleCloseCreateProviderModal}>
            <div className={styles['provider-modal']} onClick={(e) => e.stopPropagation()}>
              <div className={styles['provider-modal-header']}>
                <h3>新增供应商</h3>
              </div>
              <div className={styles['provider-modal-body']}>
                <div className={styles['form-group']}>
                  <label>供应商标识</label>
                  <input
                    type="text"
                    value={addProviderForm.provider}
                    onChange={(e) => setAddProviderForm(prev => ({ ...prev, provider: e.target.value }))}
                    placeholder="例如 free-api"
                  />
                </div>
                <div className={styles['form-group']}>
                  <label>显示名称（可选）</label>
                  <input
                    type="text"
                    value={addProviderForm.display_name}
                    onChange={(e) => setAddProviderForm(prev => ({ ...prev, display_name: e.target.value }))}
                    placeholder="例如 Free API"
                  />
                </div>
                <div className={styles['form-group']}>
                  <label>图标地址（可选）</label>
                  <input
                    type="text"
                    value={addProviderForm.icon}
                    onChange={(e) => setAddProviderForm(prev => ({ ...prev, icon: e.target.value }))}
                    placeholder="https://example.com/icon.png"
                  />
                </div>
                <div className={styles['form-group']}>
                  <label>默认模型（可选）</label>
                  <input
                    type="text"
                    value={addProviderForm.base_model}
                    onChange={(e) => setAddProviderForm(prev => ({ ...prev, base_model: e.target.value }))}
                    placeholder="custom-model"
                  />
                </div>
                <div className={styles['form-group']}>
                  <label>API URL（可选）</label>
                  <input
                    type="text"
                    value={addProviderForm.api_endpoint}
                    onChange={(e) => setAddProviderForm(prev => ({ ...prev, api_endpoint: e.target.value }))}
                    placeholder="https://api.example.com/v1/chat/completions"
                  />
                </div>
                <div className={styles['form-group']}>
                  <label>API Key（可选）</label>
                  <input
                    type="password"
                    ref={addProviderApiKeyInputRef}
                    defaultValue=""
                    autoComplete="new-password"
                    placeholder="输入供应商 API Key"
                  />
                </div>
                <div className={styles['form-group']}>
                  <label>最大 Token 数（可选）</label>
                  <input
                    type="number"
                    value={addProviderForm.max_tokens}
                    onChange={(e) => setAddProviderForm(prev => ({ ...prev, max_tokens: e.target.value === '' ? '' : Number(e.target.value) }))}
                    placeholder="例如 4096"
                    min="1"
                  />
                </div>
              </div>
              <div className={styles['provider-modal-actions']}>
                <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={handleCloseCreateProviderModal} disabled={creatingProvider}>取消</button>
                <button className={`btn btn-primary`} onClick={handleCreateProvider} disabled={creatingProvider}>
                  {creatingProvider ? '创建中...' : '确认创建'}
                </button>
              </div>
            </div>
          </div>
        )}

        {showDeleteConfirmModal && (
          <div className={styles['provider-modal-overlay']} onClick={handleCloseDeleteConfirmModal}>
            <div className={styles['provider-modal']} onClick={(e) => e.stopPropagation()}>
              <div className={styles['provider-modal-header']}>
                <h3>确认删除</h3>
              </div>
              <div className={styles['provider-modal-body']}>
                <p style={{ margin: '16px 0', lineHeight: 1.5 }}>
                  确定要删除供应商“<strong>{providerForm.display_name.trim() || providerForm.provider}</strong>”吗？<br />
                  该供应商下的配置将被永久删除，此操作不可恢复。
                </p>
              </div>
              <div className={styles['provider-modal-footer']}>
                <button 
                  className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} 
                  onClick={handleCloseDeleteConfirmModal} 
                  disabled={deletingProvider}
                >
                  取消
                </button>
                <button 
                  className={`btn ${styles['btn-danger'] || 'btn-danger'}`} 
                  onClick={confirmDeleteProvider} 
                  disabled={deletingProvider}
                >
                  {deletingProvider ? '删除中...' : '确认删除'}
                </button>
              </div>
            </div>
          </div>
        )}

        {showImportModal && (
          <div className={styles['provider-modal-overlay']} onClick={() => setShowImportModal(false)}>
            <div className={styles['provider-modal']} onClick={(e) => e.stopPropagation()} style={{ maxWidth: '600px', maxHeight: '80vh', display: 'flex', flexDirection: 'column' }}>
              <div className={styles['provider-modal-header']}>
                <h3>导入模型</h3>
              </div>
              <div className={styles['provider-modal-body']} style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>
                <p style={{ marginBottom: '16px', color: 'var(--text-secondary)' }}>请勾选需要导入的模型，未勾选的模型不会出现在聊天界面中。</p>
                <div className={styles['provider-model-list']} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '12px' }}>
                  {fetchedRemoteModels.map(model => {
                    const checked = modalSelectedModels.includes(model.model)
                    return (
                      <label key={model.id || model.model} className={styles['provider-model-item']}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setModalSelectedModels(prev => [...prev, model.model])
                            } else {
                              setModalSelectedModels(prev => prev.filter(m => m !== model.model))
                            }
                          }}
                        />
                        <span className={styles['provider-model-name']}>{model.model}</span>
                      </label>
                    )
                  })}
                </div>
              </div>
              <div className={styles['provider-modal-footer']} style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', padding: '16px', borderTop: '1px solid var(--border-color)' }}>
                <button 
                  className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} 
                  onClick={() => setShowImportModal(false)} 
                  disabled={importing}
                >
                  取消
                </button>
                <button 
                  className={`btn btn-primary`} 
                  onClick={handleImportModels} 
                  disabled={importing}
                >
                  {importing ? '导入中...' : '确认导入'}
                </button>
              </div>
            </div>
          </div>
        )}

        {showDeleteModelsModal && (
          <div className={styles['provider-modal-overlay']} onClick={() => setShowDeleteModelsModal(false)}>
            <div className={styles['provider-modal']} onClick={(e) => e.stopPropagation()}>
              <div className={styles['provider-modal-header']}>
                <h3>确认批量删除</h3>
              </div>
              <div className={styles['provider-modal-body']}>
                <p style={{ margin: '16px 0', lineHeight: 1.5 }}>
                  确定要删除选中的 <strong>{selectedForDeletion.length}</strong> 个模型吗？<br />
                  这些模型将从当前配置中移除。
                </p>
              </div>
              <div className={styles['provider-modal-footer']}>
                <button 
                  className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} 
                  onClick={() => setShowDeleteModelsModal(false)} 
                  disabled={deletingModels}
                >
                  取消
                </button>
                <button 
                  className={`btn ${styles['btn-danger'] || 'btn-danger'}`} 
                  onClick={handleBatchDeleteModels} 
                  disabled={deletingModels}
                >
                  {deletingModels ? '删除中...' : '确认删除'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </PageLayout>
  )
}

export default SettingsPage
