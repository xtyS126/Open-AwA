/**
 * Input 输入框组件 — 统一表单输入样式。
 * 支持 label、错误提示、辅助文本。
 */
import { type InputHTMLAttributes, forwardRef } from 'react'
import styles from './Input.module.css'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  helperText?: string
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, helperText, className = '', id, ...rest }, ref) => {
    const inputId = id || (label ? `input-${label.replace(/\s+/g, '-').toLowerCase()}` : undefined)

    return (
      <div className={`${styles.wrapper} ${className}`}>
        {label && (
          <label htmlFor={inputId} className={styles.label}>
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={`${styles.input} ${error ? styles.hasError : ''}`}
          aria-invalid={!!error}
          aria-describedby={error ? `${inputId}-error` : helperText ? `${inputId}-helper` : undefined}
          {...rest}
        />
        {error && (
          <span id={`${inputId}-error`} className={styles.error} role="alert">
            {error}
          </span>
        )}
        {helperText && !error && (
          <span id={`${inputId}-helper`} className={styles.helper}>
            {helperText}
          </span>
        )}
      </div>
    )
  }
)

Input.displayName = 'Input'
export { Input }
export type { InputProps }
