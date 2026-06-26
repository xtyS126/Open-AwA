/**
 * Toggle 切换开关组件 —— 对齐 Canvas 设计参考。
 * md 尺寸 40x22px，sm 尺寸 32x18px；圆形 thumb 在激活时向右平移。
 * 使用 button + role="switch" 保证可访问性。
 */
import React, { useCallback } from 'react'
import styles from './Toggle.module.css'

type ToggleSize = 'sm' | 'md'

interface ToggleProps {
  /** 是否激活 */
  checked: boolean
  /** 状态变更回调，参数为新状态 */
  onChange: (checked: boolean) => void
  /** 是否禁用 */
  disabled?: boolean
  /** 尺寸，默认 md */
  size?: ToggleSize
  /** 无障碍标签 */
  'aria-label'?: string
  /** 自定义类名 */
  className?: string
}

const Toggle: React.FC<ToggleProps> = ({
  checked,
  onChange,
  disabled = false,
  size = 'md',
  'aria-label': ariaLabel,
  className = '',
}) => {
  // 点击或键盘触发时翻转状态
  const handleClick = useCallback(() => {
    if (disabled) return
    onChange(!checked)
  }, [disabled, checked, onChange])

  // 键盘交互：空格 / 回车切换
  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>) => {
      if (disabled) return
      if (event.key === ' ' || event.key === 'Enter') {
        event.preventDefault()
        onChange(!checked)
      }
    },
    [disabled, checked, onChange]
  )

  const containerCls = [
    styles.toggle,
    styles[size],
    checked ? styles.active : '',
    disabled ? styles.disabled : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <button
      type="button"
      role="switch"
      className={containerCls}
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
    >
      <span className={styles.thumb} aria-hidden="true" />
    </button>
  )
}

export { Toggle }
export type { ToggleProps, ToggleSize }
