/**
 * 提示词配置组件
 * 自定义AI助手的行为和角色提示词
 */
import styles from '../SettingsPage.module.css'

interface PromptsTabProps {
  /** 提示词内容 */
  promptContent: string
  /** 是否正在保存 */
  saving: boolean

  /** 提示词变更回调 */
  onPromptChange: (content: string) => void
  /** 保存回调 */
  onSave: () => void
}

export function PromptsTab({
  promptContent,
  saving,
  onPromptChange,
  onSave,
}: PromptsTabProps) {
  return (
    <div className={styles['settings-section']}>
      <h2>提示词配置</h2>
      <p className={styles['section-desc']}>
        自定义AI助手的行为和角色提示词
      </p>
      <textarea
        className={styles['prompt-editor']}
        value={promptContent}
        onChange={(e) => onPromptChange(e.target.value)}
        placeholder="输入系统提示词..."
        rows={12}
      />
      <div className={styles['prompt-helper']}>
        <p>支持的变量：{'{user_name}'} - 用户名，{'{current_time}'} - 当前时间</p>
      </div>
      <button
        className={`btn btn-primary`}
        onClick={onSave}
        disabled={saving}
      >
        {saving ? '保存中...' : '保存提示词'}
      </button>
    </div>
  )
}

export default PromptsTab
