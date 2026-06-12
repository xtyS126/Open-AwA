/**
 * 新增供应商模态框组件
 */
import { PROVIDER_NAMES } from '@/assets/providers'
import { getPresetProviderBaseUrl } from '@/features/settings/SettingsPage.utils'
import styles from '@/features/settings/SettingsPage.module.css'

interface AddProviderFormState {
  provider: string
  display_name: string
  api_endpoint: string
  is_custom: boolean
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
  if (!isOpen) {
    return null
  }

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
              onChange={(e) => {
                const val = e.target.value
                if (val === '__custom__') {
                  onChangeForm({
                    provider: '',
                    display_name: '',
                    api_endpoint: '',
                    is_custom: true,
                  })
                } else {
                  onChangeForm({
                    provider: val,
                    display_name: PROVIDER_NAMES[val] || val,
                    api_endpoint: getPresetProviderBaseUrl(val),
                    is_custom: false,
                  })
                }
              }}
            >
              <option value="">请选择供应商</option>
              {Object.entries(PROVIDER_NAMES).map(([id, name]) => (
                <option key={id} value={id}>{id} — {name}</option>
              ))}
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
