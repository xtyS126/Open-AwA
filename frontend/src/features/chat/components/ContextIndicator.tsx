/**
 * 上下文 Token 指示器 — 显示当前对话的 Token 使用量和压缩状态。
 * 支持点击手动触发上下文压缩 (/compact)。
 */
import React, { useState, useCallback } from 'react'
import { useI18nStore } from '@/i18n'
import { magicCommandsApi } from '@/shared/api/magicCommandsApi'
import styles from './ContextIndicator.module.css'

interface ContextIndicatorProps {
  used: number
  budget: number
  isCompressing: boolean
  compressionCount: number
  sessionId?: string
  workspaceId?: string
  modelName?: string
  onCompact?: () => void
}

const ContextIndicator: React.FC<ContextIndicatorProps> = ({
  used,
  budget,
  isCompressing,
  compressionCount,
  sessionId,
  workspaceId,
  modelName,
  onCompact,
}) => {
  const { t } = useI18nStore()
  const ratio = budget > 0 ? Math.min(used / budget, 1) : 0
  const percentage = Math.round(ratio * 100)
  const barColor = ratio > 0.9 ? '#dc2626' : ratio > 0.7 ? '#f59e0b' : '#22c55e'
  const [localCompressing, setLocalCompressing] = useState(false)
  const [message, setMessage] = useState('')

  const effectiveCompressing = isCompressing || localCompressing

  const handleClick = useCallback(async () => {
    if (onCompact) {
      onCompact()
      return
    }
    if (!sessionId || effectiveCompressing) return
    setLocalCompressing(true)
    setMessage('')
    try {
      const result = await magicCommandsApi.compact(sessionId, workspaceId, modelName)
      if (result.compressed) {
        setMessage(`已压缩，移除 ${result.removed_count} 条`)
      } else {
        setMessage(result.message || '无需压缩')
      }
    } catch {
      setMessage('压缩失败')
    } finally {
      setLocalCompressing(false)
    }
  }, [sessionId, workspaceId, modelName, effectiveCompressing, onCompact])

  return (
    <div
      className={`${styles.indicator} ${(sessionId || onCompact) ? styles.clickable : ''}`}
      title={`Token: ${used}/${budget} (${percentage}%)`}
      onClick={handleClick}
    >
      <div className={styles.barBg}>
        <div
          className={`${styles.bar} ${effectiveCompressing ? styles.compress : ''}`}
          style={{ width: `${Math.max(percentage, 2)}%`, background: barColor }}
        />
      </div>
      <span className={styles.text}>
        {effectiveCompressing ? (t('chat.context.compressing') || '压缩中') : `${percentage}%`}
        {compressionCount > 0 && <span className={styles.count}> ({compressionCount})</span>}
      </span>
      {message && <span className={styles.message}>{message}</span>}
    </div>
  )
}

export default React.memo(ContextIndicator)
