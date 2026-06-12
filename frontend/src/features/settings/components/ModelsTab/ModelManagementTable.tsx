/**
 * 模型配置表格组件
 */
import type { ModelConfiguration } from '@/features/settings/modelsApi'
import { getProviderIcon } from '@/assets/providers'
import { formatTokenCount } from '@/features/settings/SettingsPage.utils.tsx'
import styles from '@/features/settings/SettingsPage.module.css'

interface ConfigModelOption {
  key: string
  configId: number
  provider: string
  providerDisplayName: string
  modelName: string
  configuration: ModelConfiguration
}

interface ModelManagementTableProps {
  /** 配置列表 */
  configs: ModelConfiguration[]
  /** 当前选中的配置选项 */
  selectedOption: ConfigModelOption | null
  /** 提供商名称映射 */
  providerNameMap: Record<string, string>
  /** 是否正在加载 */
  loading: boolean

  /** 设为默认回调 */
  onSetDefault: (configId: number) => void
  /** 编辑配置回调 */
  onEdit: (config: ModelConfiguration) => void
  /** 删除配置回调 */
  onDelete: (configId: number) => void
}

export function ModelManagementTable({
  configs,
  selectedOption,
  providerNameMap,
  loading,
  onSetDefault,
  onEdit,
  onDelete,
}: ModelManagementTableProps) {
  if (loading) {
    return <div className={styles['loading']}>加载中...</div>
  }

  if (configs.length === 0) {
    return (
      <div className={styles['empty-state']}>
        <p>暂无配置的模型</p>
        <p className={styles['hint']}>点击上方"添加模型"按钮来配置第一个模型</p>
      </div>
    )
  }

  return (
    <div className={styles['model-mgmt-table-wrapper']}>
      <h3>模型列表</h3>
      <table className={styles['model-mgmt-table']}>
        <thead>
          <tr>
            <th>图标</th>
            <th>模型名</th>
            <th>提供者</th>
            <th>规格</th>
            <th>模态</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {configs.map(config => {
            const contextWindow = config.model_spec?.context_window
            const isSelected = selectedOption?.configId === config.id
            return (
              <tr key={config.id} className={isSelected ? styles['selected-row'] : ''}>
                <td>
                  <span className={styles['model-icon-badge']}>
                    {(() => {
                      const icon = config.icon || getProviderIcon(config.provider)
                      if (icon) {
                        return <img src={icon} alt={config.provider} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      }
                      return config.provider.charAt(0).toUpperCase()
                    })()}
                  </span>
                </td>
                <td>
                  <div className={styles['model-name-cell']}>
                    {config.display_name || config.model}
                    {config.is_default && <span className={styles['default-badge']}>默认</span>}
                  </div>
                </td>
                <td>{providerNameMap[config.provider] || config.provider}</td>
                <td>{contextWindow ? formatTokenCount(contextWindow) : '-'}</td>
                <td>
                  <span className={`${styles['modality-badge']} ${
                    config.is_multimodal ? styles['modality-multimodal'] :
                    config.supports_vision ? styles['modality-vision'] :
                    styles['modality-text']
                  }`}>
                    {config.is_multimodal ? '文本+图像+音视频' :
                     config.supports_vision ? '文本+图像' :
                     '文本'}
                  </span>
                </td>
                <td>
                  <span className={`${styles['status-badge']} ${styles[`status-${config.status || 'active'}`]}`}>
                    {config.status || 'active'}
                  </span>
                </td>
                <td>
                  <div className={styles['table-actions']}>
                    {!config.is_default && (
                      <button
                        className={`btn ${styles['btn-small']}`}
                        onClick={() => onSetDefault(config.id)}
                      >
                        设为默认
                      </button>
                    )}
                    <button
                      className={`btn ${styles['btn-small']}`}
                      onClick={() => onEdit(config)}
                    >
                      编辑
                    </button>
                    <button
                      className={`btn ${styles['btn-small']} ${styles['btn-danger']}`}
                      onClick={() => onDelete(config.id)}
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
  )
}

export default ModelManagementTable
