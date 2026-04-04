import { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { promptsAPI, conversationAPI, ConversationRecordItem, ConversationCollectionStatusResponse } from '@/shared/api/api'
import { billingAPI, ModelPricing, RetentionConfig } from '@/features/billing/billingApi'
import { modelsAPI, ModelConfiguration, ModelProvider, ProviderDetailResponse, ProviderModel, ProviderModelsResponse } from '@/features/settings/modelsApi'
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
    base_model: ''
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

  const [selectedProviderId, setSelectedProviderId] = useState('')
  const [loadingApiProviders, setLoadingApiProviders] = useState(false)
  const [loadingProviderDetail, setLoadingProviderDetail] = useState(false)
  const [loadingProviderModels, setLoadingProviderModels] = useState(false)
  const [providerModelsError, setProviderModelsError] = useState<string | null>(null)
  const [hasFetchedModels, setHasFetchedModels] = useState(false)
  const [showCreateProviderModal, setShowCreateProviderModal] = useState(false)
  const [creatingProvider, setCreatingProvider] = useState(false)
  const [deletingProvider, setDeletingProvider] = useState(false)
  const [addProviderForm, setAddProviderForm] = useState(createInitialAddProviderForm())
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
      setConfigurations(configsRes.data.configurations || [])
      setProviders(providersRes.data.providers || [])
    } catch (error) {
      console.error('Failed to load models data')
    } finally {
      setLoadingConfigs(false)
    }
  }


  const normalizeProviderId = (value: string) => value.trim().toLowerCase().replace(/\s+/g, '-')

  const providerEndpointSuffixMap: Record<string, string> = {
    openai: '/v1/chat/completions',
    deepseek: '/v1/chat/completions',
    moonshot: '/v1/chat/completions',
    alibaba: '/compatible-mode/v1/chat/completions',
    zhipu: '/api/paas/v4/chat/completions',
    anthropic: '/v1/messages',
    google: '/v1beta/models'
  }

  const normalizeProviderApiEndpoint = (provider: string, apiEndpoint: string) => {
    const raw = apiEndpoint.trim()
    if (!raw) {
      return { endpoint: '', autoCompleted: false }
    }

    const normalizedProvider = normalizeProviderId(provider)
    const defaultSuffix = providerEndpointSuffixMap[normalizedProvider] || '/v1/chat/completions'
    const knownSuffixes = Array.from(new Set([...Object.values(providerEndpointSuffixMap), defaultSuffix]))

    const trimmed = raw.replace(/\/+$/, '')
    const lowerTrimmed = trimmed.toLowerCase()
    if (knownSuffixes.some((suffix) => lowerTrimmed.endsWith(suffix.toLowerCase()))) {
      return { endpoint: trimmed, autoCompleted: false }
    }

    let pathName = ''
    try {
      pathName = new URL(raw).pathname.toLowerCase()
    } catch {
      pathName = ''
    }

    const isBasePath = pathName === '' || pathName === '/' || pathName === '/v1' || pathName === '/v1beta' || pathName === '/api'
    if (!isBasePath) {
      return { endpoint: trimmed, autoCompleted: false }
    }

    return {
      endpoint: `${trimmed}${defaultSuffix}`,
      autoCompleted: true
    }
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
          selected_models: []
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
        api_endpoint: (config.api_endpoint || (config as any).api_url || (config as any).base_url || providerData.api_endpoint || (providerData as any).api_url || (providerData as any).base_url || ''),
        api_key: '',
        has_api_key: Boolean(config.has_api_key ?? providerData.has_api_key),
        selected_models: selectedModels
      })
      setSelectedProviderId(providerId)
      setHasFetchedModels(false)

      await fetchProviderModels(providerId, selectedModels)
    } catch (error) {
      setMessage({ type: 'error', text: '加载供应商详情失败' })
      setTimeout(() => setMessage(null), 3000)
    } finally {
      setLoadingProviderDetail(false)
    }
  }

  const fetchProviderModels = async (providerId: string, fallbackSelectedModels: string[] = []) => {
    if (!providerId) return

    setLoadingProviderModels(true)

    try {
      setProviderModelsError(null)
      const response = await modelsAPI.getModelsByProvider(providerId)
      const data = response.data as ProviderModelsResponse
      const selectedModels = Array.isArray(data.selected_models)
        ? data.selected_models
        : fallbackSelectedModels

      setProviderModels(data.models || [])
      setProviderForm(prev => ({ ...prev, selected_models: selectedModels }))

      if (!data.success && data.error?.message) {
        setProviderModelsError(data.error.message)
      }
    } catch (error) {
      setProviderModels([])
      setProviderModelsError('获取模型列表失败')
    } finally {
      setHasFetchedModels(true)
      setLoadingProviderModels(false)
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

  const handleCreateProvider = async () => {
    const providerId = normalizeProviderId(addProviderForm.provider)
    const baseModel = addProviderForm.base_model.trim() || 'custom-model'

    if (!providerId) {
      setMessage({ type: 'error', text: '请输入供应商标识' })
      setTimeout(() => setMessage(null), 3000)
      return
    }

    setCreatingProvider(true)

    try {
      const normalizedEndpointResult = normalizeProviderApiEndpoint(providerId, addProviderForm.api_endpoint)
      await modelsAPI.createConfiguration({
        provider: providerId,
        model: baseModel,
        display_name: addProviderForm.display_name.trim() || providerId,
        icon: addProviderForm.icon.trim() || undefined,
        api_endpoint: normalizedEndpointResult.endpoint || undefined,
        api_key: addProviderForm.api_key.trim() || undefined,
        selected_models: [],
        is_default: false
      })

      setAddProviderForm(createInitialAddProviderForm())
      setShowCreateProviderModal(false)
      setMessage({ type: 'success', text: normalizedEndpointResult.autoCompleted ? '供应商创建成功，已自动补全 API URL 后缀' : '供应商创建成功' })
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

    setSaving(true)

    try {
      const normalizedEndpointResult = normalizeProviderApiEndpoint(providerForm.provider, providerForm.api_endpoint)
      const updatePayload: {
        display_name?: string
        icon?: string
        api_endpoint?: string
        api_key?: string
        selected_models?: string[]
      } = {
        display_name: providerForm.display_name.trim() || undefined,
        icon: providerForm.icon.trim() || undefined,
        api_endpoint: normalizedEndpointResult.endpoint || undefined,
        selected_models: providerForm.selected_models
      }

      if (providerForm.api_key.trim()) {
        updatePayload.api_key = providerForm.api_key.trim()
      }

      setProviderForm(prev => ({ ...prev, api_endpoint: normalizedEndpointResult.endpoint }))
      await modelsAPI.updateConfiguration(providerForm.config_id, updatePayload)
      await modelsAPI.updateProviderSelectedModels(providerForm.provider, {
        selected_models: providerForm.selected_models
      })

      setMessage({ type: 'success', text: normalizedEndpointResult.autoCompleted ? '供应商配置保存成功，已自动补全 API URL 后缀' : '供应商配置保存成功' })
      setTimeout(() => setMessage(null), 3000)
      await loadApiProvidersData(providerForm.provider)
    } catch (error) {
      setMessage({ type: 'error', text: '保存供应商配置失败' })
      setTimeout(() => setMessage(null), 3000)
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteProvider = async () => {
    if (!providerForm.provider) {
      setMessage({ type: 'error', text: '当前供应商配置不完整' })
      setTimeout(() => setMessage(null), 3000)
      return
    }

    const providerLabel = providerForm.display_name.trim() || providerForm.provider
    const confirmed = confirm(`确定要删除供应商“${providerLabel}”吗？该供应商下的配置将被删除。`)
    if (!confirmed) return

    setDeletingProvider(true)

    try {
      await modelsAPI.deleteProvider(providerForm.provider)
      setMessage({ type: 'success', text: '供应商删除成功' })
      setTimeout(() => setMessage(null), 3000)
      await loadApiProvidersData()
    } catch (error) {
      setMessage({ type: 'error', text: '供应商删除失败' })
      setTimeout(() => setMessage(null), 3000)
    } finally {
      setDeletingProvider(false)
    }
  }

  const handleToggleProviderModel = (modelName: string, checked: boolean) => {
    setProviderForm(prev => {
      const selected = checked
        ? Array.from(new Set([...prev.selected_models, modelName]))
        : prev.selected_models.filter(item => item !== modelName)

      return {
        ...prev,
        selected_models: selected
      }
    })

    setProviderModels(prev => prev.map(item => (
      item.model === modelName ? { ...item, selected: checked } : item
    )))
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
            <p className={styles['section-desc']}>左侧管理供应商，右侧配置 API URL、API Key，并获取模型后用复选框选择。</p>

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
                        <label>API URL</label>
                        <input
                          type="text"
                          value={providerForm.api_endpoint}
                          onChange={(e) => setProviderForm(prev => ({ ...prev, api_endpoint: e.target.value }))}
                          placeholder="https://api.example.com/v1/chat/completions"
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
                    </div>

                    <div className={styles['provider-detail-actions']}>
                      <button
                        type="button"
                        className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
                        onClick={() => fetchProviderModels(providerForm.provider, providerForm.selected_models)}
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
                        onClick={handleDeleteProvider}
                        disabled={deletingProvider}
                      >
                        {deletingProvider ? '删除中...' : '删除供应商'}
                      </button>
                    </div>

                    <div className={styles['provider-models-section']}>
                      <h3>模型选择（复选）</h3>
                      {providerModelsError && (
                        <div className={`${styles['message']} ${styles['error']}`}>{providerModelsError}</div>
                      )}
                      {loadingProviderModels ? (
                        <div className={styles['loading']}>加载模型中...</div>
                      ) : providerModels.length === 0 ? (
                        <div className={styles['empty-state']}>
                          {hasFetchedModels ? (
                            <p>该供应商暂无模型配置。请在下方的“添加模型”中录入。</p>
                          ) : (
                            <p>暂无模型，请先点击“获取模型列表”</p>
                          )}
                        </div>
                      ) : (
                        <div className={styles['provider-model-list']}>
                          {providerModels.map(model => {
                            const checked = providerForm.selected_models.includes(model.model)
                            return (
                              <label key={model.id} className={styles['provider-model-item']}>
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={(e) => handleToggleProviderModel(model.model, e.target.checked)}
                                />
                                <span className={styles['provider-model-name']}>{model.model}</span>
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
              配置可用的AI模型，设置的默认模型将自动在聊天页面选中
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

            {loadingConfigs ? (
              <div className={styles['loading']}>加载中...</div>
            ) : configurations.length === 0 ? (
              <div className={styles['empty-state']}>
                <p>暂无配置的模型</p>
                <p className={styles['hint']}>点击上方"添加模型"按钮来配置第一个模型</p>
              </div>
            ) : (
              <div className={styles['configs-list']}>
                {configurations.map(config => (
                  <div key={config.id} className={`${styles['config-card']} ${config.is_default ? styles['default'] : ''}`}>
                    <div className={styles['config-info']}>
                      <div className={styles['config-header']}>
                        <span className={styles['config-provider']}>{getProviderName(config.provider)}</span>
                        {config.is_default && <span className={styles['default-badge']}>默认</span>}
                      </div>
                      <div className={styles['config-model']}>{config.display_name || config.model}</div>
                      {config.description && (
                        <div className={styles['config-description']}>{config.description}</div>
                      )}
                      <div className={styles['config-meta']}>
                        模型：{config.model}
                      </div>
                    </div>
                    <div className={styles['config-actions']}>
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
                  </div>
                ))}
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
      </div>
    </div>
  )
}

export default SettingsPage
