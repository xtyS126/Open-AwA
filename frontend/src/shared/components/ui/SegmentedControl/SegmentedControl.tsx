/**
 * SegmentedControl 分段控制器 — 用于在多个互斥选项中切换。
 * 支持滑动指示器动画和等宽布局。
 */
import React, { useMemo } from 'react'
import styles from './SegmentedControl.module.css'

interface SegmentedOption {
  value: string
  label: string
}

interface SegmentedControlProps {
  options: SegmentedOption[]
  value: string
  onChange: (value: string) => void
  className?: string
}

const SegmentedControl: React.FC<SegmentedControlProps> = ({
  options,
  value,
  onChange,
  className = '',
}) => {
  const activeIndex = useMemo(
    () => options.findIndex((opt) => opt.value === value),
    [options, value]
  )

  return (
    <div
      className={[styles.container, className].filter(Boolean).join(' ')}
      role="group"
    >
      {/* 滑动指示器 */}
      <div
        className={styles.indicator}
        style={{
          width: `${100 / options.length}%`,
          transform: `translateX(${activeIndex * 100}%)`,
        }}
      />
      {/* 选项按钮 */}
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={[styles.option, opt.value === value ? styles.active : ''].filter(Boolean).join(' ')}
          aria-pressed={opt.value === value}
          onClick={() => onChange(opt.value)}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

export { SegmentedControl }
export type { SegmentedControlProps, SegmentedOption }
