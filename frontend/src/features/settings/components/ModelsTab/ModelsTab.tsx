/**
 * 模型配置管理组件
 * 配置可用的AI模型参数，设置的默认模型将自动在聊天页面选中
 */
import { useMemo } from 'react'
import type { ModelConfiguration, ModelProvider, ProviderModel } from '@/features/settings/modelsApi'
import { AddConfigForm } from './AddConfigForm'
import { ModelManagementTable } from './ModelManagementTable'
import { MODALITY_TYPES, MODALITY_LABELS } from '@/features/settings/SettingsPage.utils'
import { Badge } from '@/shared/components/ui/Badge'
import { getProviderIcon } from '@/assets/providers'
import styles from '@/features/settings/SettingsPage.module.css'

interface ConfigModelOption {
  key: string
  configId: number
  provider: string
  providerDisplayName: string
  modelName: string
  configuration: ModelConfiguration
}

/** 表单字段值的类型：文本输入为 string，复选框为 boolean */
type FormFieldValue = string | boolean

interface ModelsTabProps {
  /** 是否显示添加表单 */
  showAddForm: boolean
  /** 配置列表 */
  configurations: ModelConfiguration[]
  /** 是否正在加载 */
  loading: boolean
  /** 提供商列表 */
  providers: ModelProvider[]
  /** 提供商模型列表（用于添加表单的模型下拉框，仅包含当前选中提供商的模型） */
  providerModels: ProviderModel[]
  /** 当前选中的配置选项 */
  selectedOption: ConfigModelOption | null
  /** 编辑中的配置ID */
  editingConfigId: number | null
  /** 编辑表单数据 */
  editConfigForm: {
    display_name: string
    description: string
    input_modality: string[]
    output_modality: string[]
  }
  /** 是否正在保存编辑 */
  savingEdit: boolean
  /** 提供商名称映射 */
  providerNameMap: Record<string, string>
  /** 新配置表单数据 */
  newConfig: {
    provider: string
    model: string
    display_name: string
    description: string
    is_default: boolean
  }

  /** 切换添加表单显示 */
  onToggleAddForm: () => void
  /** 提供商变更回调 */
  onProviderChange: (provider: string) => void
  /** 模型变更回调 */
  onModelChange: (model: string) => void
  /** 表单字段变更回调 */
  onFieldChange: (field: string, value: FormFieldValue) => void
  /** 添加配置回调 */
  onAddConfiguration: () => void
  /** 编辑配置回调 */
  onEditConfig: (config: ModelConfiguration) => void
  /** 保存编辑回调 */
  onSaveConfigEdit: () => void
  /** 取消编辑回调 */
  onCancelEdit: () => void
  /** 模态字段变更回调 */
  onEditFormChange: (field: string, value: FormFieldValue) => void
  /** 切换模态类型回调 */
  onToggleModality: (direction: 'input' | 'output', modality: string) => void
  /** 删除配置回调 */
  onDeleteConfiguration: (configId: number) => void
  /** 设为默认回调 */
  onSetDefault: (configId: number) => void
}

export function ModelsTab({
  showAddForm,
  configurations,
  loading,
  providers,
  providerModels,
  selectedOption,
  editingConfigId,
  editConfigForm,
  savingEdit,
  providerNameMap,
  newConfig,
  onToggleAddForm,
  onProviderChange,
  onModelChange,
  onFieldChange,
  onAddConfiguration,
  onEditConfig,
  onSaveConfigEdit,
  onCancelEdit,
  onEditFormChange,
  onToggleModality,
  onDeleteConfiguration,
  onSetDefault,
}: ModelsTabProps) {
  // 找到当前编辑的配置
  const editingConfig = useMemo(() => {
    if (editingConfigId === null) return null
    return configurations.find(c => c.id === editingConfigId) || null
  }, [configurations, editingConfigId])

  // 计算每个供应商的模型配置数量
  const providerModelCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    configurations.forEach(config => {
      counts[config.provider] = (counts[config.provider] || 0) + 1
    })
    return counts
  }, [configurations])

  // 模态类型常量（已从 utils 导入）

  return (
    <div className={styles['settings-section']}>
      <div className={styles['section-header']}>
        <h2>模型管理</h2>
        <button
          className={`btn btn-primary`}
          onClick={onToggleAddForm}
        >
          {showAddForm ? '取消' : '+ 添加模型'}
        </button>
      </div>
      <p className={styles['section-desc']}>
        配置可用的AI模型参数，设置的默认模型将自动在聊天页面选中
      </p>

      {/* 添加配置表单 */}
      {showAddForm && (
        <AddConfigForm
          show={true}
          newConfig={newConfig}
          providers={providers}
          providerModels={providerModels}
          adding={false}
          onClose={onToggleAddForm}
          onProviderChange={onProviderChange}
          onModelChange={onModelChange}
          onFieldChange={onFieldChange}
          onAdd={onAddConfiguration}
        />
      )}

      {/* 供应商卡片网格（对齐 Canvas 设计参考）*/}
      {providers.length > 0 && (
        <div className={styles['provider-cards-section']}>
          <div className={styles['provider-cards-header']}>
            <h2>模型配置</h2>
          </div>
          <div className={styles['provider-cards-grid']}>
            {providers.map(provider => {
              // 获取供应商图标
              const icon = provider.icon || getProviderIcon(provider.id)
              // 判断连接状态：ollama 为本地，其余依据 has_api_key/api_key_status
              const isLocal = provider.id.toLowerCase() === 'ollama'
              const isConnected = !isLocal && (provider.has_api_key === true || provider.api_key_status === 'active')
              const modelCount = provider.configuration_count ?? providerModelCounts[provider.id] ?? 0
              const displayName = provider.display_name || provider.name || providerNameMap[provider.id] || provider.id

              return (
                <div key={provider.id} className={styles['provider-card']}>
                  {/* 供应商品牌图标盒子（44x44 圆角）*/}
                  <div className={styles['provider-card-icon']}>
                    {icon ? (
                      <img src={icon} alt={displayName} loading="lazy" decoding="async" />
                    ) : (
                      <span style={{ color: '#fff', fontSize: '18px', fontWeight: 600 }}>
                        {displayName.charAt(0).toUpperCase()}
                      </span>
                    )}
                  </div>
                  {/* 中间内容：名称 + 状态徽标 + 模型数量 */}
                  <div className={styles['provider-card-body']}>
                    <div className={styles['provider-card-title-row']}>
                      <span className={styles['provider-card-name']}>{displayName}</span>
                      {isLocal ? (
                        <Badge variant="warning" text="本地" />
                      ) : isConnected ? (
                        <Badge variant="success" text="已连接" />
                      ) : null}
                    </div>
                    <p className={styles['provider-card-sub']}>
                      {modelCount > 0 ? `${modelCount} 个模型已配置` : '暂无模型配置'}
                    </p>
                  </div>
                  {/* 配置按钮 */}
                  <button
                    className={styles['provider-card-config-btn']}
                    onClick={onToggleAddForm}
                  >
                    配置
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* 模型配置表格 */}
      <ModelManagementTable
        configs={configurations}
        selectedOption={selectedOption}
        providerNameMap={providerNameMap}
        loading={loading}
        onSetDefault={onSetDefault}
        onEdit={onEditConfig}
        onDelete={onDeleteConfiguration}
      />

      {/* 编辑模态框 */}
      {editingConfigId !== null && editingConfig && (
        <div className={styles['modal-overlay']} onClick={() => onCancelEdit()}>
          <div className={styles['modal-content']} style={{ maxWidth: '520px' }} onClick={(e) => e.stopPropagation()}>
            <div className={styles['modal-header']}>
              <h3>编辑模型信息</h3>
              <button className={styles['modal-close']} onClick={onCancelEdit} aria-label="关闭编辑模型弹窗">×</button>
            </div>
            <div className={styles['modal-body']}>
              <div className={styles['form-group']}>
                <label>模型</label>
                <input
                  type="text"
                  value={`${editingConfig.provider} / ${editingConfig.model}`}
                  disabled
                  style={{ background: '#f3f4f6', color: '#6b7280' }}
                />
              </div>
              <div className={styles['form-group']}>
                <label>显示名称</label>
                <input
                  type="text"
                  value={editConfigForm.display_name}
                  onChange={(e) => onEditFormChange('display_name', e.target.value)}
                  placeholder="例如：GPT-4o"
                />
              </div>
              <div className={styles['form-group']}>
                <label>描述</label>
                <input
                  type="text"
                  value={editConfigForm.description}
                  onChange={(e) => onEditFormChange('description', e.target.value)}
                  placeholder="模型描述"
                />
              </div>
              <div className={styles['form-group']}>
                <label>输入模态（模型能接收的内容类型）</label>
                <div className={styles['modality-checkbox-group']}>
                  {MODALITY_TYPES.map(mt => {
                    const isLastChecked = editConfigForm.input_modality.includes(mt) && editConfigForm.input_modality.length <= 1
                    return (
                      <label key={`in-${mt}`} className={styles['modality-checkbox-label']}>
                        <input
                          type="checkbox"
                          checked={editConfigForm.input_modality.includes(mt)}
                          disabled={isLastChecked}
                          onChange={() => onToggleModality('input', mt)}
                        />
                        <span>{MODALITY_LABELS[mt]}</span>
                      </label>
                    )
                  })}
                </div>
              </div>
              <div className={styles['form-group']}>
                <label>输出模态（模型能生成的内容类型）</label>
                <div className={styles['modality-checkbox-group']}>
                  {MODALITY_TYPES.map(mt => {
                    const isLastChecked = editConfigForm.output_modality.includes(mt) && editConfigForm.output_modality.length <= 1
                    return (
                      <label key={`out-${mt}`} className={styles['modality-checkbox-label']}>
                        <input
                          type="checkbox"
                          checked={editConfigForm.output_modality.includes(mt)}
                          disabled={isLastChecked}
                          onChange={() => onToggleModality('output', mt)}
                        />
                        <span>{MODALITY_LABELS[mt]}</span>
                      </label>
                    )
                  })}
                </div>
              </div>
            </div>
            <div className={styles['modal-footer']}>
              <button className="btn" onClick={onCancelEdit}>取消</button>
              <button className="btn btn-primary" onClick={onSaveConfigEdit} disabled={savingEdit}>
                {savingEdit ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default ModelsTab
