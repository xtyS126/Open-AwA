import type { LayerData } from './soulApi'
import styles from './ProfileCard.module.css'

/** 五层画像的层级名称映射 */
const LAYER_LABELS: Record<string, string> = {
  surface: '表层 - 基础信息',
  interest: '兴趣层 - 偏好与兴趣',
  role: '角色层 - 社会角色',
  values: '价值观层 - 信念与价值观',
  core: '核心层 - 深层特质',
}

interface ProfileCardProps {
  layerName: string
  layerData: LayerData
  isExpanded: boolean
  onToggle: () => void
}

/** 以百分比展示置信度 */
function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`
}

export default function ProfileCard({
  layerName,
  layerData,
  isExpanded,
  onToggle,
}: ProfileCardProps) {
  const label = LAYER_LABELS[layerName] || layerName

  return (
    <div className={styles['profile-card']}>
      <button
        className={styles['card-header']}
        onClick={onToggle}
        aria-expanded={isExpanded}
        type="button"
      >
        <div className={styles['header-left']}>
          <span className={styles['expand-icon']}>
            {isExpanded ? '\u25BC' : '\u25B6'}
          </span>
          <h3 className={styles['layer-name']}>{label}</h3>
        </div>
        <div className={styles['header-right']}>
          <span className={styles['confidence-badge']}>
            置信度 {formatConfidence(layerData.confidence)}
          </span>
        </div>
      </button>

      {isExpanded && (
        <div className={styles['card-body']}>
          <p className={styles['description']}>{layerData.description}</p>

          {layerData.structured_data &&
            Object.keys(layerData.structured_data).length > 0 && (
              <div className={styles['structured-section']}>
                <h4 className={styles['section-title']}>结构化数据</h4>
                <table className={styles['data-table']}>
                  <tbody>
                    {Object.entries(layerData.structured_data).map(
                      ([key, value]) => (
                        <tr key={key}>
                          <td className={styles['data-key']}>{key}</td>
                          <td className={styles['data-value']}>
                            {formatValue(value)}
                          </td>
                        </tr>
                      )
                    )}
                  </tbody>
                </table>
              </div>
            )}
        </div>
      )}
    </div>
  )
}

/** 将结构化数据值格式化为可展示的字符串 */
function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '-'
  }
  if (typeof value === 'boolean') {
    return value ? '是' : '否'
  }
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join(', ')
  }
  if (typeof value === 'object') {
    return JSON.stringify(value)
  }
  return String(value)
}