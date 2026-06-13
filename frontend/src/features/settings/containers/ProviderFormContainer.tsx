/**
 * 供应商表单容器 Hook
 * 管理供应商表单相关的状态和逻辑，包括供应商的创建、编辑、删除，
 * 以及模型导入/批量删除等功能。
 *
 * 将原本 ApiTabContainer 中与供应商表单直接相关的状态和操作
 * 提取为独立的自定义 Hook，实现关注点分离。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { modelsAPI } from '@/features/settings/modelsApi'
import type {
  ModelProvider,
  ProviderDetailResponse,
  ProviderModel,
  ProviderModelsResponse,
  OllamaModel,
  ProviderConnectionStatus,
  ModelConfiguration,
} from '@/features/settings/modelsApi'
import { getApiErrorDetail } from '@/shared/api/client'
import { useNotification } from '@/shared/hooks/useNotification'
import { appLogger } from '@/shared/utils/logger'
import {
  normalizeProviderId,
  normalizeProviderBaseUrl,
} from '@/features/settings/SettingsPage.utils'

/** 供应商表单状态接口 */
export interface ApiProviderFormState {
  config_id: number | null
  provider: string
  display_name: string
  icon: string
  api_endpoint: string
  api_key: string
  has_api_key: boolean
  selected_models: string[]
  masked_api_key: string | null
}

/** 添加供应商表单状态接口 */
export interface AddProviderFormState {
  provider: string
  display_name: string
  api_endpoint: string
  is_custom: boolean
}

/** useProviderForm Hook 的入参接口 */
export interface UseProviderFormParams {
  /** 所有配置记录（用于导入模型时判断是否已存在） */
  configurations: ModelConfiguration[]
  /** 更新供应商列表的回调 */
  setProviders: (providers: ModelProvider[]) => void
  /** 加载模型配置数据的回调 */
  loadModelsData: () => Promise<void>
  /** 标记 Tab 缓存失效的回调 */
  invalidateTabCache: (tabs: string[]) => void
}

/** useProviderForm Hook 的返回值接口 */
export interface UseProviderFormReturn {
  // 通知消息
  message: ReturnType<typeof useNotification>['message']
  showNotification: ReturnType<typeof useNotification>['showNotification']

  // 供应商表单状态
  providerForm: ApiProviderFormState
  setProviderForm: React.Dispatch<React.SetStateAction<ApiProviderFormState>>
  selectedProviderId: string
  setSelectedProviderId: React.Dispatch<React.SetStateAction<string>>
  loadingApiProviders: boolean
  loadingProviderDetail: boolean
  loadingProviderModels: boolean
  providerModelsError: string | null
  providerStatuses: ProviderConnectionStatus[]
  loadingProviderStatuses: boolean
  ollamaModels: OllamaModel[]
  loadingOllama: boolean
  ollamaError: string | null
  saving: boolean
  deletingProvider: boolean

  // API Key 显示/隐藏状态
  showApiKey: boolean
  setShowApiKey: React.Dispatch<React.SetStateAction<boolean>>

  // 模型导入/删除状态
  selectedForDeletion: string[]
  setSelectedForDeletion: React.Dispatch<React.SetStateAction<string[]>>
  showDeleteModelsModal: boolean
  setShowDeleteModelsModal: React.Dispatch<React.SetStateAction<boolean>>
  deletingModels: boolean

  // 创建供应商模态框状态
  showCreateProviderModal: boolean
  setShowCreateProviderModal: React.Dispatch<React.SetStateAction<boolean>>
  addProviderForm: AddProviderFormState
  setAddProviderForm: React.Dispatch<React.SetStateAction<AddProviderFormState>>
  creatingProvider: boolean

  // 删除确认模态框状态
  showDeleteConfirmModal: boolean
  setShowDeleteConfirmModal: React.Dispatch<React.SetStateAction<boolean>>

  // 导入模型模态框状态
  showImportModal: boolean
  setShowImportModal: React.Dispatch<React.SetStateAction<boolean>>
  fetchedRemoteModels: ProviderModel[]
  modalSelectedModels: string[]
  setModalSelectedModels: React.Dispatch<React.SetStateAction<string[]>>
  importing: boolean

  // Refs
  providerApiKeyInputRef: React.RefObject<HTMLInputElement | null>

  // 回调函数
  handleOpenCreateProviderModal: () => void
  handleCloseCreateProviderModal: () => void
  handleCreateProvider: () => Promise<void>
  handleOpenDeleteConfirmModal: () => void
  handleCloseDeleteConfirmModal: () => void
  confirmDeleteProvider: () => Promise<void>
  handleSaveProviderConfig: () => Promise<void>
  fetchProviderModels: (
    providerId: string,
    fallbackSelectedModels?: string[],
    openModal?: boolean,
    credentials?: { api_endpoint?: string; api_key?: string }
  ) => Promise<void>
  handleDiscoverOllamaModels: () => Promise<void>
  handleCheckProviderStatuses: () => Promise<void>
  loadProviderDetail: (providerId: string) => Promise<void>
  loadApiProvidersData: (preferredProviderId?: string) => Promise<void>
  handleImportModels: () => Promise<void>
  handleBatchDeleteModels: () => Promise<void>
}

/**
 * 供应商表单管理 Hook
 *
 * 封装供应商表单相关的所有状态和操作逻辑，包括：
 * - 供应商表单的增删改查
 * - 模型导入和批量删除
 * - Ollama 模型发现
 * - 供应商连接状态检查
 */
export function useProviderForm({
  configurations,
  setProviders,
  loadModelsData,
  invalidateTabCache,
}: UseProviderFormParams): UseProviderFormReturn {
  const { message, showNotification } = useNotification(3000)

  // 供应商表单状态
  const [providerForm, setProviderForm] = useState<ApiProviderFormState>({
    config_id: null,
    provider: '',
    display_name: '',
    icon: '',
    api_endpoint: '',
    api_key: '',
    has_api_key: false,
    selected_models: [],
    masked_api_key: null
  })
  const [showApiKey, setShowApiKey] = useState(false)
  const [selectedProviderId, setSelectedProviderId] = useState('')
  const [loadingApiProviders, setLoadingApiProviders] = useState(false)
  const [loadingProviderDetail, setLoadingProviderDetail] = useState(false)
  const [loadingProviderModels, setLoadingProviderModels] = useState(false)
  const [providerModelsError, setProviderModelsError] = useState<string | null>(null)

  // 供应商连接状态
  const [providerStatuses, setProviderStatuses] = useState<ProviderConnectionStatus[]>([])
  const [loadingProviderStatuses, setLoadingProviderStatuses] = useState(false)

  // Ollama 模型发现相关状态
  const [ollamaModels, setOllamaModels] = useState<OllamaModel[]>([])
  const [loadingOllama, setLoadingOllama] = useState(false)
  const [ollamaError, setOllamaError] = useState<string | null>(null)

  // 模型导入和批量删除状态
  const [selectedForDeletion, setSelectedForDeletion] = useState<string[]>([])
  const [showDeleteModelsModal, setShowDeleteModelsModal] = useState(false)
  const [deletingModels, setDeletingModels] = useState(false)

  // 创建和删除供应商模态框状态
  const [showCreateProviderModal, setShowCreateProviderModal] = useState(false)
  const [showDeleteConfirmModal, setShowDeleteConfirmModal] = useState(false)
  const [creatingProvider, setCreatingProvider] = useState(false)
  const [deletingProvider, setDeletingProvider] = useState(false)

  // 添加供应商表单状态
  const [addProviderForm, setAddProviderForm] = useState<AddProviderFormState>({
    provider: '',
    display_name: '',
    api_endpoint: '',
    is_custom: false
  })

  // 导入模型模态框状态
  const [showImportModal, setShowImportModal] = useState(false)
  const [fetchedRemoteModels, setFetchedRemoteModels] = useState<ProviderModel[]>([])
  const [modalSelectedModels, setModalSelectedModels] = useState<string[]>([])
  const [importing, setImporting] = useState(false)

  // Refs
  const providerApiKeyInputRef = useRef<HTMLInputElement | null>(null)
  const remoteModelCacheRef = useRef<Map<string, { signature: string; fetchedAt: number; options: Array<{ id: string; provider: string; model: string; display_name: string }> }>>(new Map())
  const providerDetailsCacheRef = useRef<Map<string, ProviderDetailResponse>>(new Map())

  const [saving, setSaving] = useState(false)

  /** 创建初始添加供应商表单 */
  const createInitialAddProviderForm = useCallback((): AddProviderFormState => ({
    provider: '',
    display_name: '',
    api_endpoint: '',
    is_custom: false
  }), [])

  /** 失效远端模型缓存 */
  const invalidateRemoteModelCache = useCallback((providerId?: string) => {
    if (providerId) {
      remoteModelCacheRef.current.delete(providerId)
    } else {
      remoteModelCacheRef.current.clear()
    }
  }, [])

  /** 获取供应商模型列表 */
  const fetchProviderModels = useCallback(async (
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

      // 更新供应商表单的 selected_models，使主页面显示它们
      setProviderForm(prev => ({ ...prev, selected_models: selectedModels }))

      if (!data.success) {
        setProviderModelsError(data.error?.message || '获取模型列表失败')
        return
      }

      if (openModal) {
        // 打开模态框并预选模型
        setModalSelectedModels(selectedModels)
        setShowImportModal(true)
      }
    } catch {
      setFetchedRemoteModels([])
      setProviderModelsError('获取模型列表失败')
    } finally {
      setLoadingProviderModels(false)
    }
  }, [invalidateRemoteModelCache])

  /** 加载供应商详情 */
  const loadProviderDetail = useCallback(async (providerId: string) => {
    if (!providerId) return

    setLoadingProviderDetail(true)
    setProviderModelsError(null)

    try {
      // 先检查缓存
      let detailData = providerDetailsCacheRef.current.get(providerId)

      if (!detailData) {
        // 缓存未命中，从 API 获取
        const detailRes = await modelsAPI.getProviderDetail(providerId)
        detailData = detailRes.data as ProviderDetailResponse
        // 更新缓存
        providerDetailsCacheRef.current.set(providerId, detailData)
      }

      const config = detailData.configuration
      const providerData = detailData.provider

      const selectedModels = Array.isArray(config.selected_models)
        ? config.selected_models
        : (providerData.selected_models || [])

      const api_endpoint = (config.base_url || config.api_endpoint || (config as unknown as Record<string, unknown>).api_url || providerData.base_url || providerData.api_endpoint || (providerData as unknown as Record<string, unknown>).api_url || '') as string

      // 获取脱敏 API Key
      let maskedApiKey: string | null = null
      if (providerData.has_api_key) {
        try {
          const maskedRes = await modelsAPI.getMaskedApiKey(providerId)
          maskedApiKey = maskedRes.data.masked_api_key
        } catch {
          // 获取失败不影响主流程
        }
      }

      setProviderForm({
        config_id: config.id,
        provider: config.provider || providerId,
        display_name: config.display_name || providerData.display_name || providerData.name || providerId,
        icon: config.icon || providerData.icon || '',
        api_endpoint,
        api_key: '',
        has_api_key: Boolean(config.has_api_key ?? providerData.has_api_key),
        selected_models: selectedModels,
        masked_api_key: maskedApiKey
      })
      setSelectedProviderId(providerId)
      setShowApiKey(false)

      await fetchProviderModels(providerId, selectedModels, false, { api_endpoint })
    } catch {
      showNotification({ type: 'error', text: '加载供应商详情失败' })
    } finally {
      setLoadingProviderDetail(false)
    }
  }, [showNotification, fetchProviderModels])

  /** 加载 API 供应商数据（优化：并行获取所有供应商详情） */
  const loadApiProvidersData = useCallback(async (preferredProviderId?: string) => {
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
        setProviderForm({
          config_id: null,
          provider: '',
          display_name: '',
          icon: '',
          api_endpoint: '',
          api_key: '',
          has_api_key: false,
          selected_models: [],
          masked_api_key: null
        })
        return
      }

      // 优化：并行获取所有供应商详情
      const results = await Promise.allSettled(
        validProviders.map(provider => modelsAPI.getProviderDetail(provider.id))
      )

      // 更新缓存
      results.forEach((result, index) => {
        if (result.status === 'fulfilled') {
          providerDetailsCacheRef.current.set(
            validProviders[index].id,
            result.value.data as ProviderDetailResponse
          )
        }
      })

      const preferred = preferredProviderId || selectedProviderId
      const nextProviderId = preferred && validProviders.some(item => item.id === preferred)
        ? preferred
        : validProviders[0].id

      await loadProviderDetail(nextProviderId)
    } catch {
      showNotification({ type: 'error', text: '加载供应商列表失败' })
    } finally {
      setLoadingApiProviders(false)
    }
  }, [selectedProviderId, setProviders, showNotification, loadProviderDetail])

  /** 导入模型 */
  const handleImportModels = useCallback(async () => {
    if (!providerForm.config_id || !providerForm.provider) {
      showNotification({ type: 'error', text: '当前供应商配置不完整' })
      return
    }

    if (providerForm.api_endpoint) {
      try {
        new URL(providerForm.api_endpoint)
      } catch {
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
      invalidateTabCache(['general', 'models', 'api'])
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
            const status = (e as { response?: { status?: number } })?.response?.status
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
        loadModelsData(),
        loadApiProvidersData(providerForm.provider)
      ])
    } catch (error) {
      showNotification({ type: 'error', text: `模型导入失败：${getApiErrorDetail(error)}` })
    } finally {
      setImporting(false)
    }
  }, [providerForm, modalSelectedModels, configurations, showNotification, invalidateRemoteModelCache, invalidateTabCache, loadModelsData, loadApiProvidersData])

  /** 批量删除模型 */
  const handleBatchDeleteModels = useCallback(async () => {
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
      invalidateTabCache(['general', 'models', 'api'])
      setSelectedForDeletion([])
      showNotification({ type: 'success', text: '批量删除及配置保存成功' })
      setShowDeleteModelsModal(false)

      await Promise.all([
        loadModelsData(),
        loadApiProvidersData(providerForm.provider)
      ])
    } catch (error) {
      showNotification({ type: 'error', text: `批量删除失败：${getApiErrorDetail(error)}` })
    } finally {
      setDeletingModels(false)
    }
  }, [providerForm, selectedForDeletion, showNotification, invalidateRemoteModelCache, invalidateTabCache, loadModelsData, loadApiProvidersData])

  /** 打开创建供应商模态框 */
  const handleOpenCreateProviderModal = useCallback(() => {
    setAddProviderForm(createInitialAddProviderForm())
    setShowCreateProviderModal(true)
  }, [createInitialAddProviderForm])

  /** 关闭创建供应商模态框 */
  const handleCloseCreateProviderModal = useCallback(() => {
    if (creatingProvider) return
    setShowCreateProviderModal(false)
  }, [creatingProvider])

  /** 创建供应商 */
  const handleCreateProvider = useCallback(async () => {
    const providerId = normalizeProviderId(addProviderForm.provider)
    const nextDisplayName = addProviderForm.display_name.trim()

    if (!providerId) {
      showNotification({ type: 'error', text: '请输入供应商标识' })
      return
    }

    if (addProviderForm.api_endpoint) {
      try {
        new URL(addProviderForm.api_endpoint)
      } catch {
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
  }, [addProviderForm, showNotification, invalidateRemoteModelCache, loadApiProvidersData, createInitialAddProviderForm])

  /** 打开删除确认模态框 */
  const handleOpenDeleteConfirmModal = useCallback(() => {
    if (!providerForm.provider) {
      showNotification({ type: 'error', text: '当前供应商配置不完整' })
      return
    }
    setShowDeleteConfirmModal(true)
  }, [providerForm.provider, showNotification])

  /** 关闭删除确认模态框 */
  const handleCloseDeleteConfirmModal = useCallback(() => {
    if (deletingProvider) return
    setShowDeleteConfirmModal(false)
  }, [deletingProvider])

  /** 确认删除供应商 */
  const confirmDeleteProvider = useCallback(async () => {
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
    } catch {
      showNotification({ type: 'error', text: '供应商删除失败' })
    } finally {
      setDeletingProvider(false)
    }
  }, [providerForm.provider, showNotification, invalidateRemoteModelCache, loadApiProvidersData])

  /** 保存供应商配置 */
  const handleSaveProviderConfig = useCallback(async () => {
    if (!providerForm.provider) {
      showNotification({ type: 'error', text: '请指定供应商标识' })
      return
    }

    if (providerForm.api_endpoint) {
      try {
        new URL(providerForm.api_endpoint)
      } catch {
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
      
      // 如果更新了 API Key，刷新脱敏显示
      if (nextApiKey) {
        try {
          const maskedRes = await modelsAPI.getMaskedApiKey(providerForm.provider)
          setProviderForm(prev => ({
            ...prev,
            api_endpoint: normalizedBaseUrl,
            has_api_key: true,
            masked_api_key: maskedRes.data.masked_api_key
          }))
        } catch {
          setProviderForm(prev => ({ ...prev, api_endpoint: normalizedBaseUrl, has_api_key: true }))
        }
      } else {
        setProviderForm(prev => ({ ...prev, api_endpoint: normalizedBaseUrl }))
      }
      
      setShowApiKey(false)
      await loadApiProvidersData(providerForm.provider)
    } catch (error: unknown) {
      // 处理 409 冲突：配置已存在时尝试更新
      const status = (error as { response?: { status?: number } })?.response?.status
      if (status === 409) {
        try {
          // 查找与当前供应商匹配的所有配置，取第一个作为更新目标
          const existingConfig = configurations.find(
            c => c.provider === providerForm.provider
          )
          if (existingConfig?.id) {
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
              selected_models: providerForm.selected_models
            }
            if (nextApiKey) {
              updatePayload.api_key = nextApiKey
            }
            await modelsAPI.updateConfiguration(existingConfig.id, updatePayload)
            if (providerApiKeyInputRef.current) {
              providerApiKeyInputRef.current.value = ''
            }
            invalidateRemoteModelCache(providerForm.provider)
            showNotification({ type: 'success', text: '配置已更新' })
            await loadApiProvidersData(providerForm.provider)
          } else {
            showNotification({ type: 'error', text: '配置已存在，但无法获取 ID 进行更新' })
          }
        } catch (updateError) {
          showNotification({ type: 'error', text: `更新配置失败：${getApiErrorDetail(updateError)}` })
        }
      } else {
        showNotification({ type: 'error', text: `保存供应商配置失败：${getApiErrorDetail(error)}` })
      }
    } finally {
      setSaving(false)
    }
  }, [providerForm, configurations, showNotification, invalidateRemoteModelCache, loadApiProvidersData])

  /** 发现 Ollama 模型 */
  const handleDiscoverOllamaModels = useCallback(async () => {
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
  }, [])

  /** 检查供应商状态 */
  const handleCheckProviderStatuses = useCallback(async () => {
    setLoadingProviderStatuses(true)
    try {
      const response = await modelsAPI.getProvidersStatus()
      setProviderStatuses(response.data.providers || [])
    } catch {
      showNotification({ type: 'error', text: '获取供应商状态失败' })
    } finally {
      setLoadingProviderStatuses(false)
    }
  }, [showNotification])

  // ESC 键关闭创建供应商模态框
  useEffect(() => {
    if (!showCreateProviderModal) return

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        handleCloseCreateProviderModal()
      }
    }

    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [showCreateProviderModal, creatingProvider, handleCloseCreateProviderModal])

  // ESC 键关闭删除确认模态框
  useEffect(() => {
    if (!showDeleteConfirmModal) return

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        handleCloseDeleteConfirmModal()
      }
    }

    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [showDeleteConfirmModal, deletingProvider, handleCloseDeleteConfirmModal])

  // 首次挂载时加载 API 供应商数据
  useEffect(() => {
    loadApiProvidersData()
  }, [loadApiProvidersData])

  return {
    // 通知消息
    message,
    showNotification,

    // 供应商表单状态
    providerForm,
    setProviderForm,
    selectedProviderId,
    setSelectedProviderId,
    loadingApiProviders,
    loadingProviderDetail,
    loadingProviderModels,
    providerModelsError,
    providerStatuses,
    loadingProviderStatuses,
    ollamaModels,
    loadingOllama,
    ollamaError,
    saving,
    deletingProvider,

    // API Key 显示/隐藏状态
    showApiKey,
    setShowApiKey,

    // 模型导入/删除状态
    selectedForDeletion,
    setSelectedForDeletion,
    showDeleteModelsModal,
    setShowDeleteModelsModal,
    deletingModels,

    // 创建供应商模态框状态
    showCreateProviderModal,
    setShowCreateProviderModal,
    addProviderForm,
    setAddProviderForm,
    creatingProvider,

    // 删除确认模态框状态
    showDeleteConfirmModal,
    setShowDeleteConfirmModal,

    // 导入模型模态框状态
    showImportModal,
    setShowImportModal,
    fetchedRemoteModels,
    modalSelectedModels,
    setModalSelectedModels,
    importing,

    // Refs
    providerApiKeyInputRef,

    // 回调函数
    handleOpenCreateProviderModal,
    handleCloseCreateProviderModal,
    handleCreateProvider,
    handleOpenDeleteConfirmModal,
    handleCloseDeleteConfirmModal,
    confirmDeleteProvider,
    handleSaveProviderConfig,
    fetchProviderModels,
    handleDiscoverOllamaModels,
    handleCheckProviderStatuses,
    loadProviderDetail,
    loadApiProvidersData,
    handleImportModels,
    handleBatchDeleteModels,
  }
}
