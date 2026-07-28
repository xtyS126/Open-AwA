/**
 * 模型配置表格组件（对齐 Canvas 设计参考）
 */
import type { ModelConfiguration } from '@/features/settings/modelsApi'
import { getProviderIcon } from '@/assets/providers'
import { formatTokenCount } from '@/features/settings/SettingsPage.utils.tsx'
import { Toggle } from '@/shared/components/ui/Toggle'
import { Badge } from '@/shared/components/ui/Badge'
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
      {/* 表格容器：圆角边框 + 阴影（对齐 Canvas）*/}
      <div className={styles['model-mgmt-table-container']}>
        <table className={styles['model-mgmt-table']}>
          <thead>
            <tr>
              <th>模型名称</th>
              <th>提供者</th>
              <th>类型</th>
              <th>上下文长度</th>
              <th>状态</th>
              <th style={{ textAlign: 'right' }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {configs.map(config => {
              const contextWindow = config.model_spec?.context_window
              const isSelected = selectedOption?.configId === config.id
              // 判断模型激活状态
              const isActive = config.is_active !== false && (config.status || 'active') === 'active'
              // 判断模型类型：多模态 / 视觉 / 纯文本
              const isMultimodal = !!config.is_multimodal
              const supportsVision = !!config.supports_vision
              return (
                <tr key={config.id} className={isSelected ? styles['selected-row'] : ''}>
                  {/* 模型名称列：品牌图标 + 名称 + 默认徽标 */}
                  <td>
                    <div className={styles['model-name-cell']}>
                      <span className={styles['model-icon-badge']}>
                        {(() => {
                          const icon = config.icon || getProviderIcon(config.provider)
                          if (icon) {
                            return <img src={icon} alt={config.provider} loading="lazy" decoding="async" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                          }
                          return config.provider.charAt(0).toUpperCase()
                        })()}
                      </span>
                      <div style={{ display: 'flex', flexDirection: 'column' }}>
                        <span style={{ fontWeight: 'var(--font-medium)', color: 'var(--color-text)' }}>
                          {config.display_name || config.model}
                        </span>
                        {config.model !== (config.display_name || config.model) && (
                          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-tertiary)' }}>
                            {config.model}
                          </span>
                        )}
                        {config.is_default && <span className={styles['default-badge']}>默认</span>}
                      </div>
                    </div>
                  </td>
                  {/* 提供者列 */}
                  <td style={{ color: 'var(--color-text-secondary)' }}>
                    {providerNameMap[config.provider] || config.provider}
                  </td>
                  {/* 类型列：使用 Badge 组件（对齐 Canvas）*/}
                  <td>
                    {isMultimodal ? (
                      <Badge variant="primary" text="对话+推理" />
                    ) : supportsVision ? (
                      <Badge variant="primary" text="对话+图像" />
                    ) : (
                      <Badge variant="primary" text="对话" />
                    )}
                  </td>
                  {/* 上下文长度列 */}
                  <td style={{ color: 'var(--color-text-secondary)' }}>
                    {contextWindow ? formatTokenCount(contextWindow) : '-'}
                  </td>
                  {/* 状态列：Toggle + 启用文字（对齐 Canvas）*/}
                  <td>
                    <div className={styles['status-cell']}>
                      <Toggle
                        checked={isActive}
                        onChange={() => {
                          // 状态切换为只读展示，不触发实际变更
                        }}
                        aria-label={`模型 ${config.display_name || config.model} 启用状态`}
                      />
                      <span className={`${styles['status-text']} ${isActive ? '' : styles['inactive']}`}>
                        {isActive ? '启用' : '停用'}
                      </span>
                    </div>
                  </td>
                  {/* 操作列：编辑 + 删除按钮（边框样式，对齐 Canvas）*/}
                  <td style={{ textAlign: 'right' }}>
                    <div className={styles['table-actions']} style={{ justifyContent: 'flex-end' }}>
                      {!config.is_default && (
                        <button
                          className={styles['provider-card-config-btn']}
                          onClick={() => onSetDefault(config.id)}
                        >
                          设为默认
                        </button>
                      )}
                      <button
                        className={styles['provider-card-config-btn']}
                        onClick={() => onEdit(config)}
                      >
                        编辑
                      </button>
                      <button
                        className={`${styles['provider-card-config-btn']}`}
                        style={{ color: 'var(--color-error)', borderColor: 'var(--color-border)' }}
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
    </div>
  )
}

export default ModelManagementTable
