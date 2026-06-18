/**
 * SOLO/Builder 模式切换组件。
 * SOLO 模式：Agent 自主完成整个任务。
 * Builder 模式：逐步执行，每步等待确认。
 */
import { useState, useCallback } from 'react'
import { Zap, ListChecks } from 'lucide-react'
import styles from './ModeSwitcher.module.css'

export type ExecutionMode = 'solo' | 'builder'

interface ModeSwitcherProps {
  mode: ExecutionMode
  onModeChange: (mode: ExecutionMode) => void
}

/** SOLO/Builder 模式切换组件 */
export default function ModeSwitcher({ mode, onModeChange }: ModeSwitcherProps) {
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
        title="SOLO 模式：Agent 自主完成整个任务"
      >
        <Zap size={14} />
        <span>SOLO</span>
      </button>
      <button
        className={`${styles.modeBtn} ${mode === 'builder' ? styles.active : ''}`}
        onClick={() => handleModeChange('builder')}
        title="Builder 模式：逐步执行，每步等待确认"
      >
        <ListChecks size={14} />
        <span>Builder</span>
      </button>
      {showTooltip && (
        <div className={styles.tooltip}>
          {mode === 'solo'
            ? 'SOLO 模式：Agent 自主完成整个任务，无需逐步确认'
            : 'Builder 模式：Agent 逐步执行，每步展示计划并等待确认'}
        </div>
      )}
    </div>
  )
}
