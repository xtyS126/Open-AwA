/**
 * SOLO/Builder 模式切换组件。
 * SOLO 模式：Agent 自主完成整个任务。
 * Builder 模式：逐步执行，每步等待确认。
 */
import { useState, useCallback } from 'react'
import { Zap, ListChecks } from 'lucide-react'
import { useI18nStore } from '@/i18n'
import styles from './ModeSwitcher.module.css'

export type ExecutionMode = 'solo' | 'builder'

interface ModeSwitcherProps {
  mode: ExecutionMode
  onModeChange: (mode: ExecutionMode) => void
}

/** SOLO/Builder 模式切换组件 */
export default function ModeSwitcher({ mode, onModeChange }: ModeSwitcherProps) {
  const t = useI18nStore(s => s.t)
  const [showTooltip, setShowTooltip] = useState(false)

  const handleModeChange = useCallback((newMode: ExecutionMode) => {
    if (newMode !== mode) {
      onModeChange(newMode)
    }
  }, [mode, onModeChange])

  return (
    <div
      className={styles.container}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <button
        className={`${styles.modeBtn} ${mode === 'solo' ? styles.active : ''}`}
        onClick={() => handleModeChange('solo')}
        title={t('coding.mode.solo.title')}
      >
        <Zap size={14} />
        <span>{t('coding.mode.solo')}</span>
      </button>
      <button
        className={`${styles.modeBtn} ${mode === 'builder' ? styles.active : ''}`}
        onClick={() => handleModeChange('builder')}
        title={t('coding.mode.builder.title')}
      >
        <ListChecks size={14} />
        <span>{t('coding.mode.builder')}</span>
      </button>
      {showTooltip && (
        <div className={styles.tooltip}>
          {mode === 'solo' ? t('coding.mode.solo.tooltip') : t('coding.mode.builder.tooltip')}
        </div>
      )}
    </div>
  )
}
