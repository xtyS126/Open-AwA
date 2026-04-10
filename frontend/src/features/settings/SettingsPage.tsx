import { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { promptsAPI, conversationAPI, ConversationRecordItem, ConversationCollectionStatusResponse } from '@/shared/api/api'
import { billingAPI, ModelPricing, RetentionConfig } from '@/features/billing/billingApi'
import { modelsAPI, ModelConfiguration, ModelProvider, ProviderDetailResponse, ProviderModel, ProviderModelsResponse, ModelCapabilitiesResponse } from '@/features/settings/modelsApi'
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
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
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

  useEffect(() => {
    loadSettings()
    loadPrompts()
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
      console.error('Failed to load retention config')
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
      setMessage({ type: 'success', text: `保存成功${cleanupOld && response.data.deleted_records > 0 ? `，已删除${response.data.deleted_records}条过期记录` : ''}` })
      loadRetentionConfig()
      setCleanupOld(false)
    } catch (error) {
      setMessage({ type: 'error', text: '保存失败' })
    } finally {
      setSaving(false)
      setTimeout(() => setMessage(null), 3000)
    }
  }

  const loadSettings = () => {
    const savedSettings = localStorage.getItem('app_settings')
    if (savedSettings) {
      try {
        setSettings(JSON.parse(savedSettings))
      } catch (e) {
        console.error('Failed to load settings')
      }
    }
  }

  const loadPrompts = async () => {
    try {
      const response = await promptsAPI.getActive()
      if (response.data && response.data.content) {
        setSettings(prev => ({ ...prev, promptContent: response.data.content }))
      }
    } catch (error) {
      console.error('Failed to load prompts')
    }
  }

  const loadCollectionStatus = async () => {
    try {
      const response = await conversationAPI.getCollectionStatus()
      setCollectionEnabled(Boolean(response.data.enabled))
      setCollectionStats(response.data.stats || null)
    } catch (error) {
      setMessage({ type: 'error', text: '加载收集状态失败' })
      setTimeout(() => setMessage(null), 3000)
    }
  }

  const loadRecordsPreview = async () => {
    setLoadingRecordsPreview(true)
    try {
      const response = await conversationAPI.getRecordsPreview(20)
      setRecordsPreview(response.data.records || [])
    } catch (error) {
      setMessage({ type: 'error', text: '加载最近记录失败' })
      setTimeout(() => setMessage(null), 3000)
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
      setMessage({ type: 'success', text: enabled ? '已开启数据收集' : '已关闭数据收集' })
      setTimeout(() => setMessage(null), 3000)
    } catch (error) {
      setMessage({ type: 'error', text: '更新收集开关失败' })
      setTimeout(() => setMessage(null), 3000)
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

      setMessage({ type: 'success', text: '导出完成' })
      setTimeout(() => setMessage(null), 3000)
    } catch (error) {
      setMessage({ type: 'error', text: '导出失败' })
      setTimeout(() => setMessage(null), 3000)
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
      setMessage({ type: 'success', text: `清理完成：已删除 ${deleted} 条记录` })
      setTimeout(() => setMessage(null), 3000)
      await loadRecordsPreview()
      await loadCollectionStatus()
    } catch (error) {
      setMessage({ type: 'error', text: '清理失败' })
      setTimeout(() => setMessage(null), 3000)
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
      console.error('Failed to load billing data')
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
      console.error('Failed to load models data')
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
      setMessage({ type: 'success', text: '模型参数保存成功' })
      await loadModelsData()
    } catch {
      setMessage({ type: 'error', text: '模型参数保存失败' })
    } finally {
      setSavingModelParams(false)
      setTimeout(() => setMessage(null), 3000)
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
      setMessage({ type: 'success', text: '已重置为默认参数' })
      await loadModelsData()
    } catch {
      setMessage({ type: 'error', text: '重置失败' })
    } finally {
      setSavingModelParams(false)
      setTimeout(() => setMessage(null), 3000)
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
      setMessage({ type: 'error', text: '加载供应商列表失败' })
      setTimeout(() => setMessage(null), 3000)
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
        api_endpoint: (config.base_url || config.api_endpoint || (config as Record<string, unknown>).api_url || providerData.base_url || providerData.api_endpoint || (providerData as Record<string, unknown>).api_url || '') as string,
        api_key: '',
        has_api_key: Boolean(config.has_api_key ?? providerData.has_api_key),
        selected_models: selectedModels,
        max_tokens: config.max_tokens ?? ''
      })
      setSelectedProviderId(providerId)

      await fetchProviderModels(providerId, selectedModels, false)
    } catch (error) {
      setMessage({ type: 'error', text: '加载供应商详情失败' })
      setTimeout(() => setMessage(null), 3000)
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
      setMessage({ type: 'success', text: '模型导入成功' })
      setShowImportModal(false)
    } catch (error) {
      setMessage({ type: 'error', text: '模型导入失败' })
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
      setMessage({ type: 'success', text: '批量删除成功' })
      setShowDeleteModelsModal(false)
    } catch (error) {
      setMessage({ type: 'error', text: '批量删除失败' })
    } finally {
      setDeletingModels(false)
    }
  }

  const handleOpenCreateProviderModal = () => {
    setAddProviderForm(createInitialAddProviderForm())
    setShowCreateProviderModal(true)
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

    if (!providerId) {
      setMessage({ type: 'error', text: '请输入供应商标识' })
      setTimeout(() => setMessage(null), 3000)
      return
    }

    if (addProviderForm.api_endpoint) {
      try {
        new URL(addProviderForm.api_endpoint)
      } catch (error) {
        setMessage({ type: 'error', text: 'API URL 格式不正确，请输入包含 http:// 或 https:// 的完整链接' })
        setTimeout(() => setMessage(null), 3000)
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
        api_key: addProviderForm.api_key.trim() || undefined,
        selected_models: [],
        max_tokens: addProviderForm.max_tokens === '' ? null : Number(addProviderForm.max_tokens),
        is_default: false
      })

      setAddProviderForm(createInitialAddProviderForm())
      setShowCreateProviderModal(false)
      setMessage({ type: 'success', text: '供应商创建成功' })
      setTimeout(() => setMessage(null), 3000)
      await loadApiProvidersData(providerId)
    } catch (error) {
      setMessage({ type: 'error', text: '供应商创建失败' })
      setTimeout(() => setMessage(null), 3000)
    } finally {
      setCreatingProvider(false)
    }
  }

  const handleSaveProviderConfig = async () => {
    if (!providerForm.config_id || !providerForm.provider) {
      setMessage({ type: 'error', text: '当前供应商配置不完整' })
      setTimeout(() => setMessage(null), 3000)
      return
    }

    if (providerForm.api_endpoint) {
      try {
        new URL(providerForm.api_endpoint)
      } catch (error) {
        setMessage({ type: 'error', text: 'API URL 格式不正确，请输入包含 http:// 或 https:// 的完整链接' })
        setTimeout(() => setMessage(null), 3000)
        return
      }
    }

    setSaving(true)

    try {
      const normalizedBaseUrl = normalizeProviderBaseUrl(providerForm.api_endpoint)
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

      if (providerForm.api_key.trim()) {
        updatePayload.api_key = providerForm.api_key.trim()
      }

      setProviderForm(prev => ({ ...prev, api_endpoint: normalizedBaseUrl }))
      await modelsAPI.updateConfiguration(providerForm.config_id, updatePayload)
      await modelsAPI.updateProviderSelectedModels(providerForm.provider, {
        selected_models: providerForm.selected_models
      })

      setMessage({ type: 'success', text: '供应商配置保存成功' })
      setTimeout(() => setMessage(null), 3000)
      await loadApiProvidersData(providerForm.provider)
    } catch (error) {
      setMessage({ type: 'error', text: '保存供应商配置失败' })
      setTimeout(() => setMessage(null), 3000)
    } finally {
      setSaving(false)
    }
  }

  const handleOpenDeleteConfirmModal = () => {
    if (!providerForm.provider) {
      setMessage({ type: 'error', text: '当前供应商配置不完整' })
      setTimeout(() => setMessage(null), 3000)
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
      setMessage({ type: 'success', text: '供应商删除成功' })
      setTimeout(() => setMessage(null), 3000)
      setShowDeleteConfirmModal(false)
      await loadApiProvidersData()
    } catch (error) {
      setMessage({ type: 'error', text: '供应商删除失败' })
      setTimeout(() => setMessage(null), 3000)
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
        console.error('Failed to load provider models')
      }
    } else {
      setProviderModels([])
    }
  }

  const handleAddConfiguration = async () => {
    if (!newConfig.provider || !newConfig.model) {
      setMessage({ type: 'error', text: '请选择提供商和模型' })
      setTimeout(() => setMessage(null), 3000)
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
      setMessage({ type: 'success', text: '添加成功' })
      setNewConfig({ provider: '', model: '', display_name: '', description: '', is_default: false })
      setShowAddForm(false)
      loadModelsData()
    } catch (error) {
      setMessage({ type: 'error', text: '添加失败' })
    }
    setTimeout(() => setMessage(null), 3000)
  }

  const handleDeleteConfiguration = async (configId: number) => {
    if (!confirm('确定要删除这个模型配置吗？')) return

    try {
      await modelsAPI.deleteConfiguration(configId)
      setMessage({ type: 'success', text: '删除成功' })
      loadModelsData()
    } catch (error) {
      setMessage({ type: 'error', text: '删除失败' })
    }
    setTimeout(() => setMessage(null), 3000)
  }

  const handleSetDefault = async (configId: number) => {
    try {
      await modelsAPI.setDefaultConfiguration(configId)
      setMessage({ type: 'success', text: '设置成功' })
      loadModelsData()
    } catch (error) {
      setMessage({ type: 'error', text: '设置失败' })
    }
    setTimeout(() => setMessage(null), 3000)
  }

  const saveSettings = async () => {
    setSaving(true)
    setMessage(null)

    try {
      localStorage.setItem('app_settings', JSON.stringify(settings))
      
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

      setMessage({ type: 'success', text: '设置保存成功' })
    } catch (error) {
      setMessage({ type: 'error', text: '保存失败，请重试' })
    } finally {
      setSaving(false)
      setTimeout(() => setMessage(null), 3000)
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
      setMessage({ type: 'success', text: '价格更新成功' })
    } catch (error) {
      setMessage({ type: 'error', text: '价格更新失败' })
    }
    setTimeout(() => setMessage(null), 3000)
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

  const getProviderName = (providerId: string) => {
    const provider = providers.find(p => p.id === providerId)
    return provider ? provider.name : providerId
  }

  return (
    <div className={styles['settings-page']}>
      <div className={styles['settings-header']}>
        <h1>设置</h1>
      </div>

      <div className={styles['settings-tabs']}>
        <button
          className={`${styles['tab-btn']} ${activeTab === 'general' ? styles['active'] : ''}`}
          onClick={() => handleTabChange('general')}
        >
          通用设置
        </button>
        <button
          className={`${styles['tab-btn']} ${activeTab === 'api' ? styles['active'] : ''}`}
          onClick={() => handleTabChange('api')}
        >
          API配置
        </button>
        <button
          className={`${styles['tab-btn']} ${activeTab === 'prompts' ? styles['active'] : ''}`}
          onClick={() => handleTabChange('prompts')}
        >
          提示词
        </button>
        <button
          className={`${styles['tab-btn']} ${activeTab === 'billing' ? styles['active'] : ''}`}
          onClick={() => handleTabChange('billing')}
        >
          计费配置
        </button>
        <button
          className={`${styles['tab-btn']} ${activeTab === 'models' ? styles['active'] : ''}`}
          onClick={() => handleTabChange('models')}
        >
          模型管理
        </button>
        <button
          className={`${styles['tab-btn']} ${activeTab === 'data-retention' ? styles['active'] : ''}`}
          onClick={() => handleTabChange('data-retention')}
        >
          数据保留
        </button>
        <button
          className={`${styles['tab-btn']} ${activeTab === 'data-collection' ? styles['active'] : ''}`}
          onClick={() => handleTabChange('data-collection')}
        >
          数据采集
        </button>
        <button
          className={`${styles['tab-btn']} ${activeTab === 'security' ? styles['active'] : ''}`}
          onClick={() => handleTabChange('security')}
        >
          安全设置
        </button>
      </div>

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
                              setMessage({ type: 'error', text: '该供应商暂无可用配置，请先新增供应商配置' })
                              setTimeout(() => setMessage(null), 3000)
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
                          type="password"
                          value={providerForm.api_key}
                          onChange={(e) => setProviderForm(prev => ({ ...prev, api_key: e.target.value }))}
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

            {/* Model Parameter Configuration Panel */}
            {configurations.length > 0 && (
              <div className={styles['model-param-panel']}>
                <h3>模型参数配置</h3>
                <div className={styles['model-param-grid']}>
                  <div className={styles['form-group']}>
                    <label>模型选择</label>
                    <select
                      value={selectedModelConfigId ?? ''}
                      onChange={(e) => {
                        const id = Number(e.target.value)
                        if (id) handleSelectModelConfig(id)
                      }}
                    >
                      <option value="">选择模型</option>
                      {configurations.map(c => (
                        <option key={c.id} value={c.id}>
                          {c.display_name || c.model} ({c.provider})
                        </option>
                      ))}
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
            <h2>安全设置</h2>
            <div className={`${styles['setting-item']} ${styles['checkbox']}`}>
              <input
                type="checkbox"
                id="require-confirm"
                checked={settings.requireConfirm}
                onChange={(e) => handleChange('requireConfirm', e.target.checked)}
              />
              <label htmlFor="require-confirm">敏感操作需要确认</label>
            </div>
            <div className={`${styles['setting-item']} ${styles['checkbox']}`}>
              <input
                type="checkbox"
                id="enable-audit"
                checked={settings.enableAudit}
                onChange={(e) => handleChange('enableAudit', e.target.checked)}
              />
              <label htmlFor="enable-audit">启用审计日志</label>
            </div>
            <button
              className={`btn btn-primary`}
              onClick={saveSettings}
              disabled={saving}
            >
              {saving ? '保存中...' : '保存安全设置'}
            </button>
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
                    value={addProviderForm.api_key}
                    onChange={(e) => setAddProviderForm(prev => ({ ...prev, api_key: e.target.value }))}
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
    </div>
  )
}

export default SettingsPage
