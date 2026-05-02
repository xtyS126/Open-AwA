/**
 * 任务参数配置面板组件。
 * 根据插件命令的 JSON Schema 参数定义动态渲染表单。
 */
import { useState, useEffect, useCallback } from 'react'
import { Settings, AlertCircle } from 'lucide-react'
import styles from './TaskParameterPanel.module.css'

interface ParamSchema {
  type?: string
  title?: string
  description?: string
  default?: unknown
  enum?: unknown[]
  required?: boolean
  properties?: Record<string, ParamSchema>
}

interface Props {
  parameters: Record<string, unknown>
  onChange: (params: Record<string, unknown>) => void
  initialValues?: Record<string, unknown>
}

export default function TaskParameterPanel({
  parameters,
  onChange,
  initialValues,
}: Props) {
  const [values, setValues] = useState<Record<string, unknown>>(initialValues || {})
  const [errors, setErrors] = useState<Record<string, string>>({})

  // 从parameters schema中提取顶层属性
  const fields = useCallback((): Array<{ key: string; schema: ParamSchema }> => {
    const props = parameters?.properties
    if (!props || typeof props !== 'object') return []
    return Object.entries(props).map(([key, schema]) => ({
      key,
      schema: schema as ParamSchema,
    }))
  }, [parameters])

  useEffect(() => {
    // 初始化默认值
    const defaults: Record<string, unknown> = { ...initialValues }
    fields().forEach(({ key, schema }) => {
      if (!(key in defaults) && schema.default !== undefined) {
        defaults[key] = schema.default
      }
    })
    if (Object.keys(defaults).length > 0) {
      setValues((prev) => ({ ...defaults, ...prev }))
    }
  }, [parameters, initialValues])

  const handleChange = (key: string, value: unknown) => {
    const next = { ...values, [key]: value }
    setValues(next)

    // 基本验证
    const newErrors = { ...errors }
    const field = fields().find((f) => f.key === key)
    if (field) {
      if (field.schema.type === 'number' && typeof value === 'string' && value !== '') {
        if (isNaN(Number(value))) {
          newErrors[key] = '请输入有效数字'
        } else {
          next[key] = Number(value)
          delete newErrors[key]
        }
      } else if (value === '' || value === null || value === undefined) {
        delete newErrors[key]
      } else {
        delete newErrors[key]
      }
    }
    setErrors(newErrors)
    onChange(next)
  }

  const fieldList = fields()

  if (fieldList.length === 0) {
    return (
      <div className={styles['empty']}>
        <Settings size={20} />
        <span>该命令无需额外参数</span>
      </div>
    )
  }

  return (
    <div className={styles['container']}>
      <div className={styles['header']}>
        <Settings size={16} />
        <span>命令参数配置</span>
      </div>

      <div className={styles['fields']}>
        {fieldList.map(({ key, schema }) => {
          const value = values[key] ?? schema.default ?? ''
          const error = errors[key]
          const requiredArr = parameters?.required as string[] | undefined
          const isRequired = Array.isArray(requiredArr) && requiredArr.includes(key)

          return (
            <div key={key} className={styles['field']}>
              <label className={styles['field-label']}>
                {schema.title || key}
                {isRequired && <span className={styles['required']}>*</span>}
              </label>

              {schema.description && (
                <span className={styles['field-desc']}>{schema.description}</span>
              )}

              {/* 枚举选择 */}
              {schema.enum && Array.isArray(schema.enum) ? (
                <select
                  value={String(value)}
                  onChange={(e) => handleChange(key, e.target.value)}
                  className={styles['field-select']}
                >
                  {schema.enum.map((opt) => (
                    <option key={String(opt)} value={String(opt)}>
                      {String(opt)}
                    </option>
                  ))}
                </select>
              ) : /* 布尔开关 */
              schema.type === 'boolean' ? (
                <label className={styles['toggle']}>
                  <input
                    type="checkbox"
                    checked={!!value}
                    onChange={(e) => handleChange(key, e.target.checked)}
                  />
                  <span>{value ? '开启' : '关闭'}</span>
                </label>
              ) : /* 数字输入 */
              schema.type === 'number' || schema.type === 'integer' ? (
                <input
                  type="number"
                  value={value !== undefined && value !== null ? String(value) : ''}
                  onChange={(e) => handleChange(key, e.target.value)}
                  className={`${styles['field-input']} ${error ? styles['field-error'] : ''}`}
                  placeholder={schema.description || `输入${schema.title || key}`}
                />
              ) : /* 长文本 */
              schema.type === 'object' || schema.type === 'array' ? (
                <textarea
                  value={typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
                  onChange={(e) => {
                    try {
                      const parsed = JSON.parse(e.target.value)
                      handleChange(key, parsed)
                    } catch {
                      handleChange(key, e.target.value)
                    }
                  }}
                  className={`${styles['field-textarea']} ${error ? styles['field-error'] : ''}`}
                  rows={4}
                  placeholder={schema.description || `输入${schema.title || key}（JSON格式）`}
                />
              ) : (
                /* 默认文本输入 */
                <input
                  type="text"
                  value={value !== undefined && value !== null ? String(value) : ''}
                  onChange={(e) => handleChange(key, e.target.value)}
                  className={`${styles['field-input']} ${error ? styles['field-error'] : ''}`}
                  placeholder={schema.description || `输入${schema.title || key}`}
                />
              )}

              {error && (
                <span className={styles['error-msg']}>
                  <AlertCircle size={12} />
                  {error}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
