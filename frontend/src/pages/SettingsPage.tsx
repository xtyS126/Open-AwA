import { useState, useEffect } from 'react'
import { promptsAPI, conversationAPI, ConversationRecordItem, ConversationCollectionStatusResponse, weixinAPI } from '../services/api'
import { billingAPI, ModelPricing, RetentionConfig } from '../services/billingApi'
import { modelsAPI, ModelConfiguration, ModelProvider, ProviderDetailResponse, ProviderModel, ProviderModelsResponse } from '../services/modelsApi'
import './SettingsPage.css'

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
  const createInitialAddProviderForm = () => ({
    provider: '',
    display_name: '',
    icon: '',
    api_endpoint: '',
    api_key: '',
    base_model: ''
  })

  const [activeTab, setActiveTab] = useState('general')
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

  // Weixin Clawbot States
  const [weixinConfig, setWeixinConfig] = useState({
    account_id: '',
    token: '',
    base_url: 'https://ilinkai.weixin.qq.com',
    timeout_seconds: 15
  })
  const [loadingWeixin, setLoadingWeixin] = useState(false)
  const [savingWeixin, setSavingWeixin] = useState(false)
  const [testingWeixin, setTestingWeixin] = useState(false)
  const [weixinHealthResult, setWeixinHealthResult] = useState<{ ok: boolean, issues: string[], suggestions: string[] } | null>(null)

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
    if (activeTab === 'communication') {
      loadWeixinConfig()
    }
  }, [activeTab])

  const loadWeixinConfig = async () => {
    setLoadingWeixin(true)
    try {
      const response = await weixinAPI.getConfig()
      if (response.data) {
        setWeixinConfig({
          account_id: response.data.account_id || '',
          token: response.data.token || '',
          base_url: response.data.base_url || 'https://ilinkai.weixin.qq.com',
          timeout_seconds: response.data.timeout_seconds || 15
        })
      }
    } catch (error) {
      console.error('Failed to load weixin config')
    } finally {
      setLoadingWeixin(false)
    }
  }

  const handleSaveWeixinConfig = async () => {
    if (!weixinConfig.account_id || !weixinConfig.token) {
      setMessage({ type: 'error', text: '微信配置不完整，account_id 和 token 为必填项' })
      setTimeout(() => setMessage(null), 3000)
      return
    }
    setSavingWeixin(true)
    try {
      await weixinAPI.saveConfig(weixinConfig)
      setMessage({ type: 'success', text: '微信通讯配置保存成功' })
    } catch (error) {
      setMessage({ type: 'error', text: '微信通讯配置保存失败' })
    } finally {
      setSavingWeixin(false)
      setTimeout(() => setMessage(null), 3000)
    }
  }

  const handleTestWeixinConnection = async () => {
    if (!weixinConfig.account_id || !weixinConfig.token) {
      setMessage({ type: 'error', text: '微信配置不完整，请先填写 account_id 和 token' })
      setTimeout(() => setMessage(null), 3000)
      return
    }
    setTestingWeixin(true)
    setWeixinHealthResult(null)
    try {
      const response = await weixinAPI.healthCheck(weixinConfig)
      setWeixinHealthResult(response.data)
      if (response.data.ok) {
        setMessage({ type: 'success', text: '测试连接成功！' })
      } else {
        setMessage({ type: 'error', text: '测试连接失败，请查看下方详细结果' })
      }
    } catch (error) {
      setMessage({ type: 'error', text: '测试连接请求失败' })
    } finally {
      setTestingWeixin(false)
      setTimeout(() => setMessage(null), 3000)
    }
  }

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
    <div className="settings-page">
      <div className="settings-header">
        <h1>设置</h1>
      </div>

      <div className="settings-tabs">
        <button
          className={`tab-btn ${activeTab === 'general' ? 'active' : ''}`}
          onClick={() => setActiveTab('general')}
        >
          通用设置
        </button>
        <button
          className={`tab-btn ${activeTab === 'api' ? 'active' : ''}`}
          onClick={() => setActiveTab('api')}
        >
          API配置
        </button>
        <button
          className={`tab-btn ${activeTab === 'prompts' ? 'active' : ''}`}
          onClick={() => setActiveTab('prompts')}
        >
          提示词
        </button>
        <button
          className={`tab-btn ${activeTab === 'billing' ? 'active' : ''}`}
          onClick={() => setActiveTab('billing')}
        >
          计费配置
        </button>
        <button
          className={`tab-btn ${activeTab === 'models' ? 'active' : ''}`}
          onClick={() => setActiveTab('models')}
        >
          模型管理
        </button>
        <button
          className={`tab-btn ${activeTab === 'data-retention' ? 'active' : ''}`}
          onClick={() => setActiveTab('data-retention')}
        >
          数据保留
        </button>
        <button
          className={`tab-btn ${activeTab === 'data-collection' ? 'active' : ''}`}
          onClick={() => setActiveTab('data-collection')}
        >
          数据采集
        </button>
        <button
          className={`tab-btn ${activeTab === 'communication' ? 'active' : ''}`}
          onClick={() => setActiveTab('communication')}
        >
          通讯配置
        </button>
        <button
          className={`tab-btn ${activeTab === 'security' ? 'active' : ''}`}
          onClick={() => setActiveTab('security')}
        >
          安全设置
        </button>
      </div>

      <div className="settings-content">
        {message && (
          <div className={`message ${message.type}`}>
            {message.text}
          </div>
        )}

        {activeTab === 'general' && (
          <div className="settings-section">
            <h2>通用设置</h2>
            <div className="setting-item">
              <label>主题</label>
              <select
                value={settings.theme}
                onChange={(e) => handleChange('theme', e.target.value)}
              >
                <option value="light">浅色</option>
                <option value="dark">深色</option>
              </select>
            </div>
            <div className="setting-item">
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
              className="btn btn-primary"
              onClick={saveSettings}
              disabled={saving}
            >
              {saving ? '保存中...' : '保存设置'}
            </button>
          </div>
        )}

                        {activeTab === 'api' && (
          <div className="settings-section">
            <div className="section-header">
              <h2>API配置</h2>
              <button
                className="btn btn-primary"
                onClick={handleOpenCreateProviderModal}
              >
                新增供应商
              </button>
            </div>
            <p className="section-desc">左侧管理供应商，右侧配置 API URL、API Key，并获取模型后用复选框选择。</p>

            <div className="api-config-layout">
              <aside className="provider-sidebar">
                {loadingApiProviders ? (
                  <div className="loading">加载供应商中...</div>
                ) : providers.length === 0 ? (
                  <div className="empty-state">
                    <p>暂无供应商配置</p>
                    <p className="hint">请先添加供应商</p>
                  </div>
                ) : (
                  <div className="provider-list">
                    {providers.map(provider => {
                      const isActive = provider.id === selectedProviderId
                      const displayName = provider.display_name || provider.name || provider.id
                      return (
                        <button
                          key={provider.id}
                          className={`provider-item ${isActive ? 'active' : ''}`}
                          onClick={() => {
                            if ((provider.configuration_count || 0) === 0) {
                              setMessage({ type: 'error', text: '该供应商暂无可用配置，请先新增供应商配置' })
                              setTimeout(() => setMessage(null), 3000)
                              return
                            }
                            loadProviderDetail(provider.id)
                          }}
                        >
                          <span className="provider-avatar">
                            {provider.icon ? (
                              <img src={provider.icon} alt={displayName} />
                            ) : (
                              <span>{displayName.slice(0, 1).toUpperCase()}</span>
                            )}
                          </span>
                          <span className="provider-item-content">
                            <span className="provider-item-title">{displayName}</span>
                            <span className="provider-item-sub">{provider.id}</span>
                            {(provider.configuration_count || 0) === 0 && (
                              <span className="provider-item-empty">未配置</span>
                            )}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                )}
              </aside>

              <section className="provider-detail-panel">
                {loadingProviderDetail ? (
                  <div className="loading">加载供应商详情中...</div>
                ) : !selectedProviderId ? (
                  <div className="empty-state">
                    <p>请选择左侧供应商</p>
                  </div>
                ) : (
                  <>
                    <div className="form-row">
                      <div className="form-group">
                        <label>供应商标识</label>
                        <input type="text" value={providerForm.provider} disabled />
                      </div>
                      <div className="form-group">
                        <label>显示名称</label>
                        <input
                          type="text"
                          value={providerForm.display_name}
                          onChange={(e) => setProviderForm(prev => ({ ...prev, display_name: e.target.value }))}
                          placeholder="供应商显示名称"
                        />
                      </div>
                    </div>

                    <div className="form-row">
                      <div className="form-group">
                        <label>图标地址（可选）</label>
                        <input
                          type="text"
                          value={providerForm.icon}
                          onChange={(e) => setProviderForm(prev => ({ ...prev, icon: e.target.value }))}
                          placeholder="https://example.com/icon.png"
                        />
                      </div>
                      <div className="form-group">
                        <label>API URL</label>
                        <input
                          type="text"
                          value={providerForm.api_endpoint}
                          onChange={(e) => setProviderForm(prev => ({ ...prev, api_endpoint: e.target.value }))}
                          placeholder="https://api.example.com/v1/chat/completions"
                        />
                      </div>
                    </div>

                    <div className="form-row">
                      <div className="form-group">
                        <label>API Key</label>
                        <input
                          type="password"
                          value={providerForm.api_key}
                          onChange={(e) => setProviderForm(prev => ({ ...prev, api_key: e.target.value }))}
                          placeholder={providerForm.has_api_key ? '已配置密钥，留空表示不修改' : '输入供应商 API Key'}
                        />
                      </div>
                    </div>

                    <div className="provider-detail-actions">
                      <button
                        className="btn btn-secondary"
                        onClick={() => fetchProviderModels(providerForm.provider, providerForm.selected_models)}
                        disabled={loadingProviderModels || deletingProvider}
                      >
                        {loadingProviderModels ? '获取中...' : '获取模型列表'}
                      </button>
                      <button
                        className="btn btn-primary"
                        onClick={handleSaveProviderConfig}
                        disabled={saving || deletingProvider}
                      >
                        {saving ? '保存中...' : '保存供应商配置'}
                      </button>
                      <button
                        className="btn btn-danger"
                        onClick={handleDeleteProvider}
                        disabled={deletingProvider}
                      >
                        {deletingProvider ? '删除中...' : '删除供应商'}
                      </button>
                    </div>

                    <div className="provider-models-section">
                      <h3>模型选择（复选）</h3>
                      {providerModelsError && (
                        <div className="message error">{providerModelsError}</div>
                      )}
                      {loadingProviderModels ? (
                        <div className="loading">加载模型中...</div>
                      ) : providerModels.length === 0 ? (
                        <div className="empty-state">
                          <p>暂无模型，请先点击“获取模型列表”</p>
                        </div>
                      ) : (
                        <div className="provider-model-list">
                          {providerModels.map(model => {
                            const checked = providerForm.selected_models.includes(model.model)
                            return (
                              <label key={model.id} className="provider-model-item">
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={(e) => handleToggleProviderModel(model.model, e.target.checked)}
                                />
                                <span className="provider-model-name">{model.model}</span>
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
          <div className="settings-section">
            <h2>提示词配置</h2>
            <p className="section-desc">
              自定义AI助手的行为和角色提示词
            </p>
            <textarea
              className="prompt-editor"
              value={settings.promptContent}
              onChange={(e) => handleChange('promptContent', e.target.value)}
              placeholder="输入系统提示词..."
              rows={12}
            />
            <div className="prompt-helper">
              <p>支持的变量：{'{user_name}'} - 用户名，{'{current_time}'} - 当前时间</p>
            </div>
            <button
              className="btn btn-primary"
              onClick={saveSettings}
              disabled={saving}
            >
              {saving ? '保存中...' : '保存提示词'}
            </button>
          </div>
        )}

        {activeTab === 'billing' && (
          <div className="settings-section">
            <h2>模型价格配置</h2>
            <p className="section-desc">
              配置各AI厂商的模型API价格（单位：百万tokens）
            </p>
            
            {loadingModels ? (
              <div className="loading">加载中...</div>
            ) : (
              <div className="pricing-table-container">
                {Object.entries(groupedModels).map(([provider, providerModels]) => (
                  <div key={provider} className="pricing-provider-group">
                    <h3 className="provider-title">{provider.toUpperCase()}</h3>
                    <table className="pricing-table">
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
                            <td className="model-name">{model.model}</td>
                            <td>
                              {editingModel === model.id ? (
                                <input
                                  type="number"
                                  value={editPrices.input_price}
                                  onChange={(e) => setEditPrices(prev => ({ ...prev, input_price: e.target.value }))}
                                  className="price-input"
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
                                  className="price-input"
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
                                <div className="action-buttons">
                                  <button 
                                    className="btn btn-small btn-primary"
                                    onClick={() => handleSaveModelPrice(model.id)}
                                  >
                                    保存
                                  </button>
                                  <button 
                                    className="btn btn-small"
                                    onClick={() => setEditingModel(null)}
                                  >
                                    取消
                                  </button>
                                </div>
                              ) : (
                                <button 
                                  className="btn btn-small"
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
          <div className="settings-section">
            <div className="section-header">
              <h2>模型管理</h2>
              <button 
                className="btn btn-primary"
                onClick={() => setShowAddForm(!showAddForm)}
              >
                {showAddForm ? '取消' : '+ 添加模型'}
              </button>
            </div>
            <p className="section-desc">
              配置可用的AI模型，设置的默认模型将自动在聊天页面选中
            </p>

            {showAddForm && (
              <div className="add-config-form">
                <div className="form-row">
                  <div className="form-group">
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
                  <div className="form-group">
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
                <div className="form-row">
                  <div className="form-group">
                    <label>显示名称（可选）</label>
                    <input
                      type="text"
                      value={newConfig.display_name}
                      onChange={(e) => setNewConfig(prev => ({ ...prev, display_name: e.target.value }))}
                      placeholder="例如：GPT-4.1"
                    />
                  </div>
                </div>
                <div className="form-row">
                  <div className="form-group">
                    <label>描述（可选）</label>
                    <input
                      type="text"
                      value={newConfig.description}
                      onChange={(e) => setNewConfig(prev => ({ ...prev, description: e.target.value }))}
                      placeholder="模型描述"
                    />
                  </div>
                </div>
                <div className="form-row">
                  <div className="form-group checkbox-group">
                    <input
                      type="checkbox"
                      id="is-default-new"
                      checked={newConfig.is_default}
                      onChange={(e) => setNewConfig(prev => ({ ...prev, is_default: e.target.checked }))}
                    />
                    <label htmlFor="is-default-new">设为默认模型</label>
                  </div>
                </div>
                <button className="btn btn-primary" onClick={handleAddConfiguration}>
                  添加
                </button>
              </div>
            )}

            {loadingConfigs ? (
              <div className="loading">加载中...</div>
            ) : configurations.length === 0 ? (
              <div className="empty-state">
                <p>暂无配置的模型</p>
                <p className="hint">点击上方"添加模型"按钮来配置第一个模型</p>
              </div>
            ) : (
              <div className="configs-list">
                {configurations.map(config => (
                  <div key={config.id} className={`config-card ${config.is_default ? 'default' : ''}`}>
                    <div className="config-info">
                      <div className="config-header">
                        <span className="config-provider">{getProviderName(config.provider)}</span>
                        {config.is_default && <span className="default-badge">默认</span>}
                      </div>
                      <div className="config-model">{config.display_name || config.model}</div>
                      {config.description && (
                        <div className="config-description">{config.description}</div>
                      )}
                      <div className="config-meta">
                        模型：{config.model}
                      </div>
                    </div>
                    <div className="config-actions">
                      {!config.is_default && (
                        <button 
                          className="btn btn-small"
                          onClick={() => handleSetDefault(config.id)}
                        >
                          设为默认
                        </button>
                      )}
                      <button 
                        className="btn btn-small btn-danger"
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
          <div className="settings-section">
            <h2>对话数据采集</h2>
            <p className="section-desc">
              采集调用链数据，预览最近记录，导出 JSONL，并清理历史数据。
            </p>

            <div className="setting-item checkbox">
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
              <div className="collection-stats-grid">
                <div className="collection-stat-card">
                  <span className="collection-stat-label">队列占用</span>
                  <span className="collection-stat-value">{collectionStats.queue_size} / {collectionStats.queue_maxsize}</span>
                </div>
                <div className="collection-stat-card">
                  <span className="collection-stat-label">丢弃数量</span>
                  <span className="collection-stat-value">{collectionStats.dropped_count}</span>
                </div>
                <div className="collection-stat-card">
                  <span className="collection-stat-label">跟踪用户数</span>
                  <span className="collection-stat-value">{collectionStats.tracked_user_count}</span>
                </div>
              </div>
            )}

            <div className="collection-actions-row">
              <button className="btn btn-secondary" onClick={loadRecordsPreview} disabled={loadingRecordsPreview}>
                {loadingRecordsPreview ? '刷新中...' : '预览最近 20 条'}
              </button>
            </div>

            <div className="collection-export-panel">
              <h3>导出 JSONL</h3>
              <div className="form-row">
                <div className="form-group">
                  <label>开始时间（可选）</label>
                  <input
                    type="datetime-local"
                    value={exportStartTime}
                    onChange={(e) => setExportStartTime(e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label>结束时间（可选）</label>
                  <input
                    type="datetime-local"
                    value={exportEndTime}
                    onChange={(e) => setExportEndTime(e.target.value)}
                  />
                </div>
              </div>
              <button className="btn btn-primary" onClick={handleExportRecords} disabled={exportingRecords}>
                {exportingRecords ? '导出中...' : '导出数据集'}
              </button>
            </div>

            <div className="collection-cleanup-panel">
              <h3>清理历史数据</h3>
              <div className="form-row">
                <div className="form-group">
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
              <button className="btn btn-danger" onClick={handleCleanupRecords} disabled={cleaningRecords}>
                {cleaningRecords ? '清理中...' : '执行清理'}
              </button>
            </div>

            <div className="collection-preview-panel">
              <h3>最近记录</h3>
              {loadingRecordsPreview ? (
                <div className="loading">加载中...</div>
              ) : recordsPreview.length === 0 ? (
                <div className="empty-state">
                  <p>暂无记录</p>
                </div>
              ) : (
                <div className="collection-record-list">
                  {recordsPreview.map((record) => (
                    <div key={record.id} className="collection-record-item">
                      <div className="collection-record-row">
                        <span className="collection-record-node">{record.node_type}</span>
                        <span className={`collection-record-status ${record.status}`}>{record.status}</span>
                      </div>
                      <div className="collection-record-row muted">
                        <span>会话: {record.session_id}</span>
                        <span>{record.timestamp ? new Date(record.timestamp).toLocaleString('zh-CN') : '-'}</span>
                      </div>
                      <div className="collection-record-row muted">
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
          <div className="settings-section">
            <h2>数据保留设置</h2>
            <p className="section-desc">
              配置计费数据的保留天数，超出保留期限的数据将被自动清理
            </p>

            {loadingRetention ? (
              <div className="loading">加载中...</div>
            ) : (
              <>
                <div className="setting-item">
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
                  <div className="setting-item">
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

                <div className="setting-item checkbox">
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
                  className="btn btn-primary"
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
          <div className="settings-section">
            <h2>安全设置</h2>
            <div className="setting-item checkbox">
              <input
                type="checkbox"
                id="require-confirm"
                checked={settings.requireConfirm}
                onChange={(e) => handleChange('requireConfirm', e.target.checked)}
              />
              <label htmlFor="require-confirm">敏感操作需要确认</label>
            </div>
            <div className="setting-item checkbox">
              <input
                type="checkbox"
                id="enable-audit"
                checked={settings.enableAudit}
                onChange={(e) => handleChange('enableAudit', e.target.checked)}
              />
              <label htmlFor="enable-audit">启用审计日志</label>
            </div>
            <button
              className="btn btn-primary"
              onClick={saveSettings}
              disabled={saving}
            >
              {saving ? '保存中...' : '保存安全设置'}
            </button>
          </div>
        )}

        {activeTab === 'communication' && (
          <div className="settings-section">
            <h2>通讯配置</h2>
            <p className="section-desc" style={{ marginBottom: '20px', color: 'var(--text-secondary)' }}>配置外部通讯渠道，如微信 Clawbot 插件。</p>

            <div className="config-card" style={{ padding: '20px', border: '1px solid var(--border-color)', borderRadius: '8px', backgroundColor: 'var(--bg-secondary)' }}>
              <h3 style={{ marginBottom: '15px' }}>微信 Clawbot 配置</h3>
              {loadingWeixin ? (
                <div className="loading">加载配置中...</div>
              ) : (
                <>
                  <div className="setting-item" style={{ marginBottom: '15px' }}>
                    <label style={{ display: 'block', marginBottom: '8px' }}>Account ID <span className="required" style={{ color: '#d32f2f' }}>*</span></label>
                    <input
                      type="text"
                      value={weixinConfig.account_id}
                      onChange={(e) => setWeixinConfig({ ...weixinConfig, account_id: e.target.value })}
                      placeholder="输入微信通讯账户 ID"
                      style={{ width: '100%', padding: '8px 12px', borderRadius: '4px', border: '1px solid var(--border-color)' }}
                    />
                  </div>
                  <div className="setting-item" style={{ marginBottom: '15px' }}>
                    <label style={{ display: 'block', marginBottom: '8px' }}>Token <span className="required" style={{ color: '#d32f2f' }}>*</span></label>
                    <input
                      type="password"
                      value={weixinConfig.token}
                      onChange={(e) => setWeixinConfig({ ...weixinConfig, token: e.target.value })}
                      placeholder="输入 iLink Bot Token"
                      style={{ width: '100%', padding: '8px 12px', borderRadius: '4px', border: '1px solid var(--border-color)' }}
                    />
                  </div>
                  <div className="setting-item" style={{ marginBottom: '15px' }}>
                    <label style={{ display: 'block', marginBottom: '8px' }}>Base URL</label>
                    <input
                      type="text"
                      value={weixinConfig.base_url}
                      onChange={(e) => setWeixinConfig({ ...weixinConfig, base_url: e.target.value })}
                      placeholder="https://ilinkai.weixin.qq.com"
                      style={{ width: '100%', padding: '8px 12px', borderRadius: '4px', border: '1px solid var(--border-color)' }}
                    />
                  </div>
                  <div className="setting-item" style={{ marginBottom: '15px' }}>
                    <label style={{ display: 'block', marginBottom: '8px' }}>超时时间 (秒)</label>
                    <input
                      type="number"
                      value={weixinConfig.timeout_seconds}
                      onChange={(e) => setWeixinConfig({ ...weixinConfig, timeout_seconds: parseInt(e.target.value, 10) || 15 })}
                      placeholder="15"
                      style={{ width: '100%', padding: '8px 12px', borderRadius: '4px', border: '1px solid var(--border-color)' }}
                    />
                  </div>
                  <div className="actions-row" style={{ marginTop: '20px', display: 'flex', gap: '10px' }}>
                    <button
                      className="btn btn-primary"
                      onClick={handleSaveWeixinConfig}
                      disabled={savingWeixin}
                    >
                      {savingWeixin ? '保存中...' : '保存配置'}
                    </button>
                    <button
                      className="btn btn-secondary"
                      onClick={handleTestWeixinConnection}
                      disabled={testingWeixin}
                    >
                      {testingWeixin ? '测试中...' : '测试连接'}
                    </button>
                  </div>

                  {weixinHealthResult && (
                    <div className={`health-result ${weixinHealthResult.ok ? 'success' : 'error'}`} style={{ marginTop: '20px', padding: '15px', borderRadius: '8px', backgroundColor: weixinHealthResult.ok ? 'rgba(76, 175, 80, 0.1)' : 'rgba(244, 67, 54, 0.1)', border: `1px solid ${weixinHealthResult.ok ? '#4caf50' : '#f44336'}` }}>
                      <h4 style={{ color: weixinHealthResult.ok ? '#2e7d32' : '#c62828', marginBottom: '10px' }}>测试结果: {weixinHealthResult.ok ? '成功' : '失败'}</h4>
                      {weixinHealthResult.issues && weixinHealthResult.issues.length > 0 && (
                        <div style={{ marginTop: '10px' }}>
                          <strong style={{ color: 'var(--text-color)' }}>问题发现:</strong>
                          <ul style={{ paddingLeft: '20px', marginTop: '5px', color: 'var(--text-color)' }}>
                            {weixinHealthResult.issues.map((issue, i) => (
                              <li key={i} style={{ color: '#d32f2f' }}>{issue}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {weixinHealthResult.suggestions && weixinHealthResult.suggestions.length > 0 && (
                        <div style={{ marginTop: '10px' }}>
                          <strong style={{ color: 'var(--text-color)' }}>建议修复:</strong>
                          <ul style={{ paddingLeft: '20px', marginTop: '5px', color: 'var(--text-color)' }}>
                            {weixinHealthResult.suggestions.map((suggestion, i) => (
                              <li key={i}>{suggestion}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {weixinHealthResult.ok && (!weixinHealthResult.issues || weixinHealthResult.issues.length === 0) && (
                        <p style={{ color: '#2e7d32', marginTop: '10px' }}>配置正常，微信适配器健康检查通过。</p>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}

        {showCreateProviderModal && (
          <div className="provider-modal-overlay" onClick={handleCloseCreateProviderModal}>
            <div className="provider-modal" onClick={(e) => e.stopPropagation()}>
              <div className="provider-modal-header">
                <h3>新增供应商</h3>
              </div>
              <div className="provider-modal-body">
                <div className="form-group">
                  <label>供应商标识</label>
                  <input
                    type="text"
                    value={addProviderForm.provider}
                    onChange={(e) => setAddProviderForm(prev => ({ ...prev, provider: e.target.value }))}
                    placeholder="例如 free-api"
                  />
                </div>
                <div className="form-group">
                  <label>显示名称（可选）</label>
                  <input
                    type="text"
                    value={addProviderForm.display_name}
                    onChange={(e) => setAddProviderForm(prev => ({ ...prev, display_name: e.target.value }))}
                    placeholder="例如 Free API"
                  />
                </div>
                <div className="form-group">
                  <label>图标地址（可选）</label>
                  <input
                    type="text"
                    value={addProviderForm.icon}
                    onChange={(e) => setAddProviderForm(prev => ({ ...prev, icon: e.target.value }))}
                    placeholder="https://example.com/icon.png"
                  />
                </div>
                <div className="form-group">
                  <label>默认模型（可选）</label>
                  <input
                    type="text"
                    value={addProviderForm.base_model}
                    onChange={(e) => setAddProviderForm(prev => ({ ...prev, base_model: e.target.value }))}
                    placeholder="custom-model"
                  />
                </div>
                <div className="form-group">
                  <label>API URL（可选）</label>
                  <input
                    type="text"
                    value={addProviderForm.api_endpoint}
                    onChange={(e) => setAddProviderForm(prev => ({ ...prev, api_endpoint: e.target.value }))}
                    placeholder="https://api.example.com/v1/chat/completions"
                  />
                </div>
                <div className="form-group">
                  <label>API Key（可选）</label>
                  <input
                    type="password"
                    value={addProviderForm.api_key}
                    onChange={(e) => setAddProviderForm(prev => ({ ...prev, api_key: e.target.value }))}
                    placeholder="输入供应商 API Key"
                  />
                </div>
              </div>
              <div className="provider-modal-actions">
                <button className="btn btn-secondary" onClick={handleCloseCreateProviderModal} disabled={creatingProvider}>取消</button>
                <button className="btn btn-primary" onClick={handleCreateProvider} disabled={creatingProvider}>
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
