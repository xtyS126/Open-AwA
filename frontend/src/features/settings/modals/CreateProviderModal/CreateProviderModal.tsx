/**
 * 新增供应商模态框组件
 * 支持从供应商目录（pricing_data.json + 数据库）中选择预定义供应商，
 * 也可自定义输入供应商标识。
 */
import { useEffect, useState } from 'react'
import { modelsAPI } from '@/features/settings/modelsApi'
import type { ModelProvider, ProviderCatalogModel } from '@/features/settings/modelsApi'
import styles from '@/features/settings/SettingsPage.module.css'

interface AddProviderFormState {
  provider: string
  display_name: string
  api_endpoint: string
  is_custom: boolean
  /** 从目录选择的供应商携带的模型列表，创建后自动导入 */
  catalog_models?: ProviderCatalogModel[]
}

interface CreateProviderModalProps {
  /** 是否显示 */
  isOpen: boolean
  /** 添加表单数据 */
  addProviderForm: AddProviderFormState
  /** 是否正在创建 */
  creatingProvider: boolean

  /** 关闭回调 */
  onClose: () => void
  /** 表单变更回调 */
  onChangeForm: (form: AddProviderFormState) => void
  /** 创建回调 */
  onCreate: () => void
}

export function CreateProviderModal({
  isOpen,
  addProviderForm,
  creatingProvider,
  onClose,
  onChangeForm,
  onCreate,
}: CreateProviderModalProps) {
  const [catalogProviders, setCatalogProviders] = useState<ModelProvider[]>([])
  const [catalogLoading, setCatalogLoading] = useState(false)

  // 打开模态框时加载供应商目录
  useEffect(() => {
    if (!isOpen) return
    let cancelled = false
    setCatalogLoading(true)
    modelsAPI.getProviderCatalog()
      .then(res => {
        if (!cancelled) {
          setCatalogProviders(res.data.providers || [])
        }
      })
      .catch(() => {
        // 加载失败不影响主流程，使用空列表
      })
      .finally(() => {
        if (!cancelled) {
          setCatalogLoading(false)
        }
      })
    return () => { cancelled = true }
  }, [isOpen])

  if (!isOpen) {
    return null
  }

  // 按 source 分组：推荐供应商（pricing_data）和已配置供应商（database）
  const recommendedProviders = catalogProviders.filter(p => p.source === 'pricing_data')
  const configuredProviders = catalogProviders.filter(p => p.source === 'database')

  return (
    <div className={styles['provider-modal-overlay']} onClick={onClose}>
      <div
        className={styles['provider-modal']}
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-provider-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles['provider-modal-header']}>
          <h3 id="create-provider-modal-title">新增供应商</h3>
        </div>
        <div className={styles['provider-modal-body']}>
          <div className={styles['form-group']}>
            <label htmlFor="add-provider-select">供应商标识</label>
            <select
              id="add-provider-select"
              value={addProviderForm.is_custom ? '__custom__' : addProviderForm.provider}
              disabled={catalogLoading}
              onChange={(e) => {
                const val = e.target.value
                if (val === '__custom__') {
                  onChangeForm({
                    provider: '',
                    display_name: '',
                    api_endpoint: '',
                    is_custom: true,
                    catalog_models: [],
                  })
                } else if (val) {
                  // 从目录中查找选中的供应商，自动填充 base_url 和模型列表
                  const selected = catalogProviders.find(p => p.id === val)
                  onChangeForm({
                    provider: val,
                    display_name: selected?.name || selected?.display_name || val,
                    api_endpoint: selected?.base_url || '',
                    is_custom: false,
                    catalog_models: selected?.models || [],
                  })
                }
              }}
            >
              <option value="">{catalogLoading ? '加载中...' : '请选择供应商'}</option>
              {recommendedProviders.length > 0 && (
                <optgroup label="推荐供应商">
                  {recommendedProviders.map(p => (
                    <option key={p.id} value={p.id}>
                      {p.id} — {p.name}{p.model_count ? ` (${p.model_count} 个模型)` : ''}
                    </option>
                  ))}
                </optgroup>
              )}
              {configuredProviders.length > 0 && (
                <optgroup label="已配置供应商">
                  {configuredProviders.map(p => (
                    <option key={p.id} value={p.id} disabled>
                      {p.id} — {p.name} (已配置)
                    </option>
                  ))}
                </optgroup>
              )}
              <option value="__custom__">自定义...</option>
            </select>
            {addProviderForm.is_custom && (
              <input
                id="add-provider-custom-id"
                type="text"
                value={addProviderForm.provider}
                onChange={(e) => onChangeForm({ ...addProviderForm, provider: e.target.value })}
                placeholder="输入自定义供应商标识"
                style={{ marginTop: 8 }}
              />
            )}
          </div>
          <div className={styles['form-group']}>
            <label htmlFor="add-provider-display-name">显示名称（可选）</label>
            <input
              id="add-provider-display-name"
              type="text"
              value={addProviderForm.display_name}
              onChange={(e) => onChangeForm({ ...addProviderForm, display_name: e.target.value })}
              placeholder="例如：OpenAI"
            />
          </div>
          <div className={styles['form-group']}>
            <label htmlFor="add-provider-base-url">基础 URL（可选）</label>
            <input
              id="add-provider-base-url"
              type="text"
              value={addProviderForm.api_endpoint}
              onChange={(e) => onChangeForm({ ...addProviderForm, api_endpoint: e.target.value })}
              placeholder="https://api.example.com/v1"
            />
          </div>
          {/* 显示选中供应商的模型数量提示 */}
          {!addProviderForm.is_custom && addProviderForm.catalog_models && addProviderForm.catalog_models.length > 0 && (
            <div style={{ fontSize: '0.85em', color: '#6b7280', marginTop: 4 }}>
              创建后将自动导入 {addProviderForm.catalog_models.length} 个模型
            </div>
          )}
        </div>
        <div className={styles['provider-modal-actions']}>
          <button className={`btn ${styles['btn-secondary']}`} onClick={onClose} disabled={creatingProvider}>取消</button>
          <button className={`btn btn-primary`} onClick={onCreate} disabled={creatingProvider}>
            {creatingProvider ? '创建中...' : '确认创建'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default CreateProviderModal
