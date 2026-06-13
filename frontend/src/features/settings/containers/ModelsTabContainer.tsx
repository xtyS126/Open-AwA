/**
 * 模型管理 Tab 容器组件
 * 管理模型配置相关的所有状态和 API 调用，将数据与回调传递给 ModelsTab 展示组件
 */
import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'
import { modelsAPI } from '@/features/settings/modelsApi'
import type { ModelConfiguration, ProviderModel } from '@/features/settings/modelsApi'
import { useSharedSettingsData } from '@/features/settings/hooks/useSharedSettingsData'
import { useNotification } from '@/shared/hooks/useNotification'
import { appLogger } from '@/shared/utils/logger'
import { useGlobalModelSelection } from '@/features/settings/hooks/useGlobalModelSelection'

// 懒加载 ModelsTab 组件，减少首屏 bundle 体积
// 通过 .then() 将 barrel 的命名导出映射为 React.lazy 需要的 default 导出
const ModelsTab = lazy(() => import('@/features/settings/components/ModelsTab').then(m => ({ default: m.ModelsTab })))

/** 懒加载组件的加载占位符 */
function TabLoadingFallback() {
  return <div style={{ padding: '2rem', textAlign: 'center', color: '#9ca3af' }}>加载中...</div>
}

/** 配置模型选项类型，用于标识一个配置下的某个模型 */
interface ConfigModelOption {
  key: string
  configId: number
  provider: string
  providerDisplayName: string
  modelName: string
  configuration: ModelConfiguration
}

/** 新配置表单状态 */
interface NewConfigState {
  provider: string
  model: string
  display_name: string
  description: string
  is_default: boolean
}

/** 编辑配置表单状态 */
interface EditConfigFormState {
  display_name: string
  description: string
  input_modality: string[]
  output_modality: string[]
}

export function ModelsTabContainer() {
  const { showNotification } = useNotification(3000)

  // 添加表单相关状态
  const [showAddForm, setShowAddForm] = useState(false)
  const [newConfig, setNewConfig] = useState<NewConfigState>({
    provider: '',
    model: '',
    display_name: '',
    description: '',
    is_default: false,
  })

  // 提供商模型列表（用于添加表单的模型下拉框）
  const [providerModels, setProviderModels] = useState<ProviderModel[]>([])

  // 编辑模态框相关状态
  const [editingConfigId, setEditingConfigId] = useState<number | null>(null)
  const [editConfigForm, setEditConfigForm] = useState<EditConfigFormState>({
    display_name: '',
    description: '',
    input_modality: ['text'],
    output_modality: ['text'],
  })
  const [savingConfigEdit, setSavingConfigEdit] = useState(false)

  // 从共享 hook 获取跨 Tab 共享数据
  const {
    configurations,
    providers,
    providerNameMap,
    loadModelsData: sharedLoadModelsData,
  } = useSharedSettingsData()

  // 全局模型选择（设置默认模型时需要同步）
  const { setSelectedModel: setGlobalSelectedModel } = useGlobalModelSelection()

  // 计算当前选中的配置模型选项（取第一个配置的第一个模型）
  const selectedConfigModelOption = useMemo<ConfigModelOption | null>(() => {
    if (configurations.length === 0) return null
    const config = configurations[0]
    const candidateModels = config.selected_models && config.selected_models.length > 0
      ? config.selected_models
      : [config.model]
    const modelName = candidateModels[0]
    const providerDisplayName = providerNameMap[config.provider] || config.provider
    return {
      key: `${config.id}:${modelName}`,
      configId: config.id,
      provider: config.provider,
      providerDisplayName,
      modelName,
      configuration: config,
    }
  }, [configurations, providerNameMap])

  /** 加载模型配置数据（委托给共享 hook） */
  const loadModelsData = useCallback(async () => {
    await sharedLoadModelsData()
  }, [sharedLoadModelsData])

  /** 添加表单中提供商变更时，加载该提供商下的模型列表 */
  const handleProviderChange = useCallback(async (provider: string) => {
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
  }, [])

  /** 添加新的模型配置 */
  const handleAddConfiguration = useCallback(async () => {
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
      setProviderModels([])
      await loadModelsData()
    } catch {
      showNotification({ type: 'error', text: '添加失败' })
    }
  }, [newConfig, showNotification, loadModelsData])

  /** 删除指定的模型配置 */
  const handleDeleteConfiguration = useCallback(async (configId: number) => {
    if (!confirm('确定要删除这个模型配置吗？')) return

    try {
      await modelsAPI.deleteConfiguration(configId)
      showNotification({ type: 'success', text: '删除成功' })
      await loadModelsData()
    } catch {
      showNotification({ type: 'error', text: '删除失败' })
    }
  }, [showNotification, loadModelsData])

  /** 将指定配置设为默认模型，并同步全局选择 */
  const handleSetDefault = useCallback(async (configId: number) => {
    try {
      await modelsAPI.setDefaultConfiguration(configId)
      showNotification({ type: 'success', text: '设置成功' })

      // 同步全局模型选择
      const config = configurations.find(c => c.id === configId)
      if (config) {
        const defaultModelName = config.selected_models?.[0] || config.model
        setGlobalSelectedModel(`${config.provider}:${defaultModelName}`)
      }

      await loadModelsData()
    } catch {
      showNotification({ type: 'error', text: '设置失败' })
    }
  }, [configurations, setGlobalSelectedModel, showNotification, loadModelsData])

  /** 打开编辑模态框并回填表单数据 */
  const handleEditConfig = useCallback((config: ModelConfiguration) => {
    setEditingConfigId(config.id)
    setEditConfigForm({
      display_name: config.display_name || '',
      description: config.description || '',
      input_modality: config.input_modality?.length ? [...config.input_modality] : ['text'],
      output_modality: config.output_modality?.length ? [...config.output_modality] : ['text'],
    })
  }, [])

  /** 切换编辑表单中的模态类型（输入/输出方向） */
  const toggleModality = useCallback((direction: 'input' | 'output', modalityType: string) => {
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
  }, [showNotification])

  /** 保存编辑后的模型配置信息 */
  const handleSaveConfigEdit = useCallback(async () => {
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
      await loadModelsData()
    } catch {
      showNotification({ type: 'error', text: '保存失败' })
    } finally {
      setSavingConfigEdit(false)
    }
  }, [editingConfigId, editConfigForm, showNotification, loadModelsData])

  // 组件挂载时加载数据
  useEffect(() => {
    loadModelsData()
  }, [loadModelsData])

  return (
    <Suspense fallback={<TabLoadingFallback />}>
      <ModelsTab
        showAddForm={showAddForm}
        configurations={configurations}
        loading={false}
        providers={providers}
        providerModels={providerModels}
        selectedOption={selectedConfigModelOption}
        editingConfigId={editingConfigId}
        editConfigForm={editConfigForm}
        savingEdit={savingConfigEdit}
        providerNameMap={providerNameMap}
        newConfig={newConfig}
        onToggleAddForm={() => setShowAddForm(prev => !prev)}
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
    </Suspense>
  )
}
