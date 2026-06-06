/**
 * Button 按钮组件 — 统一按钮样式和交互行为。
 * 支持 5 种变体（primary/secondary/danger/ghost/outline）和 3 种尺寸（sm/md/lg）。
 */
import { type ButtonHTMLAttributes, forwardRef } from 'react'
import styles from './Button.module.css'

type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost' | 'outline'
type ButtonSize = 'sm' | 'md' | 'lg'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', loading = false, className = '', children, disabled, ...rest }, ref) => {
    const cls = [
      styles.btn,
      styles[variant],
      styles[size],
      loading ? styles.loading : '',
      className,
    ].filter(Boolean).join(' ')

    return (
      <button ref={ref} className={cls} disabled={disabled || loading} {...rest}>
        {loading && <span className={styles.spinner} aria-hidden="true" />}
        {children}
      </button>
    )
  }
)

Button.displayName = 'Button'
export { Button }
export type { ButtonProps, ButtonVariant, ButtonSize }
