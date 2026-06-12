/**
 * API 配置组件
 * 管理供应商侧边栏、详情表单、模型导入、连接状态检测和 Ollama 发现
 */
import type { ModelConfiguration, ModelProvider, ProviderConnectionStatus, OllamaModel } from '@/features/settings/modelsApi'
import { modelsAPI } from '@/features/settings/modelsApi'
import { getProviderIcon } from '@/assets/providers'
import { ModelConfigCard } from '@/features/settings/components/ModelConfigCard'
import type { ModelEditParams } from '@/features/settings/components/ModelParameterEditor'
import { formatModelSize, getStatusIndicator, getModelParamSummary } from '@/features/settings/SettingsPage.utils'
import styles from '@/features/settings/SettingsPage.module.css'

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

interface ApiSettingsProps {
  /** 是否正在加载供应商列表 */
  loadingApiProviders: boolean
  /** 是否正在加载供应商详情 */
  loadingProviderDetail: boolean
  /** 是否正在加载供应商模型 */
  loadingProviderModels: boolean
  /** 已导入模型获取错误 */
  providerModelsError: string | null
  /** 供应商列表 */
  providers: ModelProvider[]
  /** 当前选中的供应商 ID */
  selectedProviderId: string
  /** 供应商详情表单数据 */
  providerForm: ApiProviderFormState
  /** API Key 输入框 ref */
  providerApiKeyInputRef: React.RefObject<HTMLInputElement>
  /** 连接状态列表 */
  providerStatuses: ProviderConnectionStatus[]
  /** 是否正在加载连接状态 */
  loadingProviderStatuses: boolean
  /** Ollama 模型列表 */
  ollamaModels: OllamaModel[]
  /** 是否正在加载 Ollama */
  loadingOllama: boolean
  /** Ollama 错误信息 */
  ollamaError: string | null
  /** 是否正在保存 */
  saving: boolean
  /** 是否正在删除供应商 */
  deletingProvider: boolean
  /** 所有模型配置 */
  configurations: ModelConfiguration[]
  /** 展开的模型配置卡片集合 */
  expandedModelConfigs: Set<string>
  /** 模型编辑参数 */
  modelEditParams: Record<string, ModelEditParams>
  /** 模型保存状态 */
  savingModelConfig: Record<string, boolean>
  /** 已选中的待删除模型 */
  selectedForDeletion: string[]

  /** 创建供应商回调 */
  onOpenCreateProviderModal: () => void
  /** 供应商详情变更回调 */
  onProviderFormChange: (updater: (prev: ApiProviderFormState) => ApiProviderFormState) => void
  /** 选择供应商回调 */
  onLoadProviderDetail: (providerId: string) => void
  /** 保存供应商配置回调 */
  onSaveProviderConfig: () => void
  /** 打开删除确认回调 */
  onOpenDeleteConfirmModal: () => void
  /** 获取模型列表回调 */
  onFetchModels: (provider: string, selectedModels: string[], openModal: boolean, credentials?: { api_endpoint?: string; api_key?: string }) => void
  /** Ollama 发现回调 */
  onDiscoverOllama: () => void
  /** 连接状态检测回调 */
  onCheckProviderStatuses: () => void
  /** 切换模型配置卡片 */
  onToggleModelConfig: (modelName: string) => void
  /** 保存模型配置 */
  onSaveModelConfig: (modelName: string) => void
  /** 重置模型配置 */
  onResetModelConfig: (modelName: string) => void
  /** 更新模型编辑参数 */
  onUpdateModelEditParam: (modelName: string, field: keyof ModelEditParams, value: number) => void
  /** 批量删除选中模型变更 */
  onSelectionChange: (modelName: string, checked: boolean) => void
  /** 打开批量删除确认 */
  onOpenDeleteModelsModal: () => void
}

export function ApiSettings({
  loadingApiProviders,
  loadingProviderDetail,
  loadingProviderModels,
  providerModelsError,
  providers,
  selectedProviderId,
  providerForm,
  providerApiKeyInputRef,
  providerStatuses,
  loadingProviderStatuses,
  ollamaModels,
  loadingOllama,
  ollamaError,
  saving,
  deletingProvider,
  configurations,
  expandedModelConfigs,
  modelEditParams,
  savingModelConfig,
  selectedForDeletion,
  onOpenCreateProviderModal,
  onProviderFormChange,
  onLoadProviderDetail,
  onSaveProviderConfig,
  onOpenDeleteConfirmModal,
  onFetchModels,
  onDiscoverOllama,
  onCheckProviderStatuses,
  onToggleModelConfig,
  onSaveModelConfig,
  onResetModelConfig,
  onUpdateModelEditParam,
  onSelectionChange,
  onOpenDeleteModelsModal,
}: ApiSettingsProps) {
  return (
    <div className={styles['settings-section']}>
      <div className={styles['section-header']}>
        <h2>API配置</h2>
        <button className={`btn btn-primary`} onClick={onOpenCreateProviderModal}>
          新增供应商
        </button>
      </div>
      <p className={styles['section-desc']}>左侧管理供应商，右侧配置基础 URL、API Key，并从远端获取模型后用复选框选择。</p>

      <div className={styles['api-config-layout']}>
        {/* 供应商侧边栏 */}
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
                        return
                      }
                      onLoadProviderDetail(provider.id)
                    }}
                  >
                    <span className={styles['provider-avatar']}>
                      {(() => {
                        const localIcon = getProviderIcon(provider.id)
                        if (localIcon) {
                          return <img src={localIcon} alt={displayName} />
                        }
                        if (provider.icon) {
                          return <img src={provider.icon} alt={displayName} />
                        }
                        return <span>{displayName.slice(0, 1).toUpperCase()}</span>
                      })()}
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

        {/* 供应商详情面板 */}
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
                    onChange={(e) => onProviderFormChange(prev => ({ ...prev, display_name: e.target.value }))}
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
                    onChange={(e) => onProviderFormChange(prev => ({ ...prev, icon: e.target.value }))}
                    placeholder="https://example.com/icon.png"
                  />
                </div>
                <div className={styles['form-group']}>
                  <label>基础 URL</label>
                  <input
                    type="text"
                    value={providerForm.api_endpoint}
                    onChange={(e) => onProviderFormChange(prev => ({ ...prev, api_endpoint: e.target.value }))}
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
              </div>

              <div className={styles['provider-detail-actions']}>
                <button
                  type="button"
                  className={`btn ${styles['btn-secondary']}`}
                  onClick={async () => {
                    const nextApiKey = providerApiKeyInputRef.current?.value.trim() || ''
                    if (nextApiKey && providerForm.config_id) {
                      try {
                        await modelsAPI.updateConfiguration(providerForm.config_id, { api_key: nextApiKey })
                        onProviderFormChange(prev => ({ ...prev, has_api_key: true }))
                        if (providerApiKeyInputRef.current) {
                          providerApiKeyInputRef.current.value = ''
                        }
                      } catch {
                        // 保存失败不阻塞模型列表拉取
                      }
                    }
                    onFetchModels(providerForm.provider, providerForm.selected_models, true, {
                      api_endpoint: providerForm.api_endpoint,
                      api_key: nextApiKey || providerForm.api_key,
                    })
                  }}
                  disabled={loadingProviderModels || deletingProvider}
                >
                  {loadingProviderModels ? '获取中...' : '获取模型列表'}
                </button>
                <button
                  className={`btn btn-primary`}
                  onClick={onSaveProviderConfig}
                  disabled={saving || deletingProvider}
                >
                  {saving ? '保存中...' : '保存供应商配置'}
                </button>
                <button
                  className={`btn ${styles['btn-danger']}`}
                  onClick={onOpenDeleteConfirmModal}
                  disabled={deletingProvider}
                >
                  {deletingProvider ? '删除中...' : '删除供应商'}
                </button>
              </div>
              {providerModelsError && (
                <div className={`${styles['message']} ${styles['error']}`} style={{ marginTop: '12px' }}>{providerModelsError}</div>
              )}

              {/* 已导入模型配置 */}
              <div className={styles['provider-models-section']}>
                <div className={styles['model-config-section-header']}>
                  <h3>已导入模型配置</h3>
                  {selectedForDeletion.length > 0 && (
                    <button
                      className={`btn ${styles['btn-danger']}`}
                      onClick={onOpenDeleteModelsModal}
                    >
                      批量删除 ({selectedForDeletion.length})
                    </button>
                  )}
                </div>

                {providerForm.selected_models.length === 0 ? (
                  <div className={styles['empty-state']}>
                    <p>暂无已导入模型，请点击上方"获取模型列表"进行选择和导入</p>
                  </div>
                ) : (
                  <div className={styles['model-config-cards']}>
                    {providerForm.selected_models.map(modelName => {
                      const configKey = `${providerForm.provider}:${modelName}`
                      return (
                        <ModelConfigCard
                          key={modelName}
                          modelName={modelName}
                          params={modelEditParams[modelName]}
                          isExpanded={expandedModelConfigs.has(configKey)}
                          isSaving={savingModelConfig[modelName] ?? false}
                          checked={selectedForDeletion.includes(modelName)}
                          summary={getModelParamSummary(modelName, configurations.filter(c => c.provider === providerForm.provider))}
                          apiEndpoint={providerForm.api_endpoint || '未配置'}
                          onToggle={onToggleModelConfig}
                          onSave={onSaveModelConfig}
                          onReset={onResetModelConfig}
                          onParamChange={onUpdateModelEditParam}
                          onCheckChange={onSelectionChange}
                        />
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
            className={`btn ${styles['btn-secondary']}`}
            onClick={onCheckProviderStatuses}
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
            onClick={onDiscoverOllama}
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
  )
}

export default ApiSettings
