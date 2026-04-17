import { ChangeEvent, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import ConfirmDialog from '@/shared/components/ConfirmDialog/ConfirmDialog'
import { useToast } from '@/shared/components/Toast'
import { usePluginConfigActions, usePluginConfigSchema, usePluginList } from '@/features/plugins/hooks'
import styles from './PluginConfigPage.module.css'

type FormValue = Record<string, unknown>
type FieldErrorMap = Record<string, string>

interface JsonSchemaField {
  type?: string
  title?: string
  description?: string
  enum?: unknown[]
  default?: unknown
  pattern?: string
  minLength?: number
  maxLength?: number
  minimum?: number
  maximum?: number
  ['x-component']?: string
}

interface JsonSchemaRoot {
  type?: string
  title?: string
  properties?: Record<string, JsonSchemaField>
  required?: string[]
}

type ConfirmAction = 'reset' | 'export' | 'import' | null

function PluginConfigPage() {
  const { pluginId } = useParams<{ pluginId: string }>()
  const navigate = useNavigate()
  const { plugins, loading: pluginListLoading } = usePluginList()
  const activePluginId = pluginId && pluginId !== 'default' ? pluginId : null
  const {
    schemaPayload,
    loading: schemaLoading,
    error: schemaError,
    retry: retryLoadSchema,
  } = usePluginConfigSchema(activePluginId)
  const {
    loading: actionLoading,
    error: actionError,
    retry: retryConfigAction,
    saveConfig,
    resetConfig,
    exportConfig,
  } = usePluginConfigActions(activePluginId)
  const { addToast, ToastContainer } = useToast()
  const importInputRef = useRef<HTMLInputElement>(null)

  const [schema, setSchema] = useState<JsonSchemaRoot>({ type: 'object', properties: {}, required: [] })
  const [formValues, setFormValues] = useState<FormValue>({})
  const [defaultConfig, setDefaultConfig] = useState<FormValue>({})
  const [errors, setErrors] = useState<FieldErrorMap>({})
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null)
  const [pendingImportConfig, setPendingImportConfig] = useState<FormValue | null>(null)
  const [rollbackSnapshot, setRollbackSnapshot] = useState<FormValue | null>(null)

  const currentPlugin = useMemo(() => plugins.find((item) => item.id === pluginId) || null, [plugins, pluginId])
  const hasValidationError = useMemo(() => Object.values(errors).some(Boolean), [errors])

  useEffect(() => {
    if (pluginListLoading) {
      return
    }
    if (!plugins.length) {
      return
    }
    if (!pluginId || pluginId === 'default' || !plugins.some((item) => item.id === pluginId)) {
      navigate(`/plugins/config/${plugins[0].id}`, { replace: true })
    }
  }, [pluginListLoading, plugins, pluginId, navigate])

  useEffect(() => {
    if (!schemaPayload) {
      return
    }
    const nextSchema = normalizeSchema(schemaPayload.schema)
    const nextDefaultConfig = schemaPayload.default_config || {}
    const nextCurrentConfig = schemaPayload.current_config || {}
    const mergedConfig = {
      ...nextDefaultConfig,
      ...nextCurrentConfig,
    }
    setSchema(nextSchema)
    setDefaultConfig(nextDefaultConfig)
    setFormValues(mergedConfig)
    setErrors(validateAllFields(nextSchema, mergedConfig))
  }, [schemaPayload])

  useEffect(() => {
    if (schemaError) {
      addToast('加载插件配置失败', 'error')
    }
  }, [schemaError, addToast])

  const handleFieldChange = (fieldKey: string, fieldSchema: JsonSchemaField, value: unknown) => {
    setFormValues((prev) => {
      const next = { ...prev, [fieldKey]: value }
      setErrors((prevErrors) => ({
        ...prevErrors,
        [fieldKey]: validateField(fieldKey, fieldSchema, next[fieldKey], isFieldRequired(schema, fieldKey)),
      }))
      return next
    })
  }

  const handleSave = async () => {
    if (!activePluginId) return
    const validationErrors = validateAllFields(schema, formValues)
    setErrors(validationErrors)
    if (Object.values(validationErrors).some(Boolean)) {
      addToast('请先修正表单校验错误后再保存', 'warning')
      return
    }
    try {
      await saveConfig(formValues)
      addToast('配置已保存并写入 config.json', 'success')
    } catch {
      addToast('配置保存失败', 'error')
    }
  }

  const handleConfirmAction = async () => {
    if (!activePluginId) {
      setConfirmAction(null)
      return
    }
    try {
      if (confirmAction === 'reset') {
        const nextConfig = await resetConfig()
        setFormValues(nextConfig)
        setErrors(validateAllFields(schema, nextConfig))
        addToast('已重置为默认配置并写入 config.json', 'success')
      } else if (confirmAction === 'export') {
        const exportedConfig = await exportConfig()
        downloadConfigAsFile(exportedConfig, currentPlugin?.name || activePluginId)
        addToast('配置导出成功', 'success')
      } else if (confirmAction === 'import' && pendingImportConfig) {
        const validationErrors = validateAllFields(schema, pendingImportConfig)
        setErrors(validationErrors)
        if (Object.values(validationErrors).some(Boolean)) {
          addToast('导入配置包含非法字段值，已阻止覆盖', 'error')
          return
        }
        setRollbackSnapshot(formValues)
        await saveConfig(pendingImportConfig)
        setFormValues(pendingImportConfig)
        setPendingImportConfig(null)
        addToast('导入配置成功，已覆盖并持久化，可使用“回滚到导入前”恢复', 'success')
      }
    } catch {
      addToast('操作执行失败', 'error')
    }
    setConfirmAction(null)
  }

  const handleOpenImport = () => {
    importInputRef.current?.click()
  }

  const handleImportFileSelected = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    try {
      const fileText = await file.text()
      const parsed = JSON.parse(fileText)
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        addToast('导入文件必须是 JSON 对象', 'error')
        return
      }
      const mergedImportConfig = {
        ...defaultConfig,
        ...(parsed as FormValue),
      }
      setPendingImportConfig(mergedImportConfig)
      setConfirmAction('import')
    } catch {
      addToast('导入文件解析失败，请确认 JSON 格式正确', 'error')
    } finally {
      if (importInputRef.current) {
        importInputRef.current.value = ''
      }
    }
  }

  const handleRollbackImport = async () => {
    if (!activePluginId || !rollbackSnapshot) return
    try {
      await saveConfig(rollbackSnapshot)
      setFormValues(rollbackSnapshot)
      setErrors(validateAllFields(schema, rollbackSnapshot))
      setRollbackSnapshot(null)
      addToast('已回滚到导入前配置', 'success')
    } catch {
      addToast('回滚失败', 'error')
    }
  }

  const properties = schema.properties || {}

  return (
    <div className={styles['plugin-config-page']}>
      <div className={styles['header']}>
        <div>
          <h1>插件配置</h1>
          <p className={styles['subtitle']}>根据 schema 动态渲染表单，实时校验后保存到插件目录 config.json</p>
        </div>
        <div className={styles['header-actions']}>
          <select
            value={pluginId || ''}
            onChange={(event) => navigate(`/plugins/config/${event.target.value}`)}
            disabled={pluginListLoading || !plugins.length}
          >
            {plugins.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
          <button className="btn btn-primary" onClick={handleSave} disabled={actionLoading || schemaLoading || hasValidationError}>
            {actionLoading ? '保存中...' : '保存配置'}
          </button>
        </div>
      </div>

      {(schemaError || actionError) && (
        <div className={styles['empty-state']}>
          <span>{schemaError || actionError}</span>
          <button
            className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
            onClick={() => {
              if (schemaError) {
                retryLoadSchema()
                return
              }
              if (actionError) {
                retryConfigAction()
              }
            }}
          >
            重试
          </button>
        </div>
      )}

      <div className={styles['toolbox']}>
        <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={() => setConfirmAction('reset')} disabled={actionLoading || schemaLoading}>
          重置默认
        </button>
        <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={() => setConfirmAction('export')} disabled={actionLoading || schemaLoading}>
          导出配置
        </button>
        <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={handleOpenImport} disabled={actionLoading || schemaLoading}>
          导入配置
        </button>
        <button
          className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}
          onClick={handleRollbackImport}
          disabled={actionLoading || !rollbackSnapshot}
        >
          回滚到导入前
        </button>
        <input ref={importInputRef} type="file" accept="application/json,.json" hidden onChange={handleImportFileSelected} />
      </div>

      {schemaLoading ? (
        <div className={styles['loading']}>配置加载中...</div>
      ) : (
        <div className={styles['form-grid']}>
          {Object.entries(properties).map(([fieldKey, fieldSchema]) => (
            <label key={fieldKey} className={styles['field-card']}>
              <span className={styles['field-label']}>
                {fieldSchema.title || fieldKey}
                {isFieldRequired(schema, fieldKey) ? <em className={styles['required']}>*</em> : null}
              </span>
              <span className={styles['field-desc']}>{fieldSchema.description || ''}</span>
              {renderFieldControl({
                fieldKey,
                fieldSchema,
                value: formValues[fieldKey],
                onChange: (value) => handleFieldChange(fieldKey, fieldSchema, value),
              })}
              {errors[fieldKey] ? <span className={styles['field-error']}>{errors[fieldKey]}</span> : null}
            </label>
          ))}
          {Object.keys(properties).length === 0 ? (
            <div className={styles['empty-state']}>当前插件未声明可编辑配置项</div>
          ) : null}
        </div>
      )}

      <ConfirmDialog
        isOpen={confirmAction !== null}
        title={getConfirmTitle(confirmAction)}
        message={getConfirmMessage(confirmAction)}
        confirmText="确认"
        cancelText="取消"
        type={confirmAction === 'reset' ? 'warning' : 'info'}
        onConfirm={handleConfirmAction}
        onCancel={() => {
          setConfirmAction(null)
          if (confirmAction !== 'import') {
            setPendingImportConfig(null)
          }
        }}
      />
      <ToastContainer />
    </div>
  )
}

function renderFieldControl(props: {
  fieldKey: string
  fieldSchema: JsonSchemaField
  value: unknown
  onChange: (value: unknown) => void
}) {
  const { fieldKey, fieldSchema, value, onChange } = props
  const componentType = resolveFieldComponent(fieldSchema)

  if (componentType === 'switch') {
    return (
      <input
        type="checkbox"
        checked={Boolean(value)}
        onChange={(event) => onChange(event.target.checked)}
      />
    )
  }

  if (componentType === 'select') {
    const options = Array.isArray(fieldSchema.enum) ? fieldSchema.enum : []
    return (
      <select value={String(value ?? '')} onChange={(event) => onChange(event.target.value)}>
        {!options.includes(value) ? <option value="">请选择</option> : null}
        {options.map((option) => (
          <option key={String(option)} value={String(option)}>
            {String(option)}
          </option>
        ))}
      </select>
    )
  }

  if (componentType === 'code-editor') {
    return (
      <textarea
        className={styles['code-editor']}
        value={String(value ?? '')}
        onChange={(event) => onChange(event.target.value)}
        rows={8}
      />
    )
  }

  if (componentType === 'file-picker') {
    return (
      <div className={styles['file-picker']}>
        <input
          type="text"
          value={String(value ?? '')}
          placeholder="请输入文件路径或文件名"
          onChange={(event) => onChange(event.target.value)}
        />
        <input
          type="file"
          onChange={(event) => {
            const file = event.target.files?.[0]
            onChange(file ? file.name : '')
          }}
          aria-label={`${fieldKey}-file-picker`}
        />
      </div>
    )
  }

  if (fieldSchema.type === 'integer' || fieldSchema.type === 'number') {
    return (
      <input
        type="number"
        value={String(value ?? '')}
        onChange={(event) => onChange(event.target.value)}
      />
    )
  }

  return (
    <input
      type="text"
      value={String(value ?? '')}
      onChange={(event) => onChange(event.target.value)}
    />
  )
}

function resolveFieldComponent(fieldSchema: JsonSchemaField): 'input' | 'select' | 'switch' | 'code-editor' | 'file-picker' {
  const markedComponent = fieldSchema['x-component']
  if (markedComponent === 'select' || markedComponent === 'switch' || markedComponent === 'code-editor' || markedComponent === 'file-picker') {
    return markedComponent
  }
  if (fieldSchema.type === 'boolean') {
    return 'switch'
  }
  if (Array.isArray(fieldSchema.enum) && fieldSchema.enum.length > 0) {
    return 'select'
  }
  return 'input'
}

function normalizeSchema(schema: Record<string, unknown>): JsonSchemaRoot {
  const rawProperties = schema.properties
  const properties: Record<string, JsonSchemaField> = {}
  if (rawProperties && typeof rawProperties === 'object' && !Array.isArray(rawProperties)) {
    Object.entries(rawProperties as Record<string, unknown>).forEach(([fieldKey, rawField]) => {
      if (rawField && typeof rawField === 'object' && !Array.isArray(rawField)) {
        properties[fieldKey] = rawField as JsonSchemaField
      }
    })
  }
  const requiredList = Array.isArray(schema.required) ? schema.required.filter((item) => typeof item === 'string') as string[] : []
  return {
    type: 'object',
    title: typeof schema.title === 'string' ? schema.title : '插件配置',
    properties,
    required: requiredList,
  }
}

function isFieldRequired(schema: JsonSchemaRoot, fieldKey: string): boolean {
  return Array.isArray(schema.required) && schema.required.includes(fieldKey)
}

function validateAllFields(schema: JsonSchemaRoot, values: FormValue): FieldErrorMap {
  const properties = schema.properties || {}
  const nextErrors: FieldErrorMap = {}
  Object.entries(properties).forEach(([fieldKey, fieldSchema]) => {
    nextErrors[fieldKey] = validateField(fieldKey, fieldSchema, values[fieldKey], isFieldRequired(schema, fieldKey))
  })
  return nextErrors
}

function validateField(fieldKey: string, fieldSchema: JsonSchemaField, value: unknown, required: boolean): string {
  const isEmpty = value === undefined || value === null || value === ''
  if (required && isEmpty) {
    return `${fieldSchema.title || fieldKey}为必填项`
  }
  if (isEmpty) {
    return ''
  }

  if (fieldSchema.type === 'integer' || fieldSchema.type === 'number') {
    const numberValue = Number(value)
    if (Number.isNaN(numberValue)) {
      return `${fieldSchema.title || fieldKey}必须是数字`
    }
    if (typeof fieldSchema.minimum === 'number' && numberValue < fieldSchema.minimum) {
      return `${fieldSchema.title || fieldKey}不能小于 ${fieldSchema.minimum}`
    }
    if (typeof fieldSchema.maximum === 'number' && numberValue > fieldSchema.maximum) {
      return `${fieldSchema.title || fieldKey}不能大于 ${fieldSchema.maximum}`
    }
    if (fieldSchema.type === 'integer' && !Number.isInteger(numberValue)) {
      return `${fieldSchema.title || fieldKey}必须是整数`
    }
  }

  if (fieldSchema.type === 'boolean' && typeof value !== 'boolean') {
    return `${fieldSchema.title || fieldKey}必须是布尔值`
  }

  if (fieldSchema.type === 'string') {
    const stringValue = String(value)
    if (typeof fieldSchema.minLength === 'number' && stringValue.length < fieldSchema.minLength) {
      return `${fieldSchema.title || fieldKey}长度不能小于 ${fieldSchema.minLength}`
    }
    if (typeof fieldSchema.maxLength === 'number' && stringValue.length > fieldSchema.maxLength) {
      return `${fieldSchema.title || fieldKey}长度不能大于 ${fieldSchema.maxLength}`
    }
    if (fieldSchema.pattern) {
      try {
        const reg = new RegExp(fieldSchema.pattern)
        if (!reg.test(stringValue)) {
          return `${fieldSchema.title || fieldKey}格式不合法`
        }
      } catch {
        return `${fieldSchema.title || fieldKey}配置的校验规则无效`
      }
    }
  }

  if (Array.isArray(fieldSchema.enum) && fieldSchema.enum.length > 0 && !fieldSchema.enum.includes(value)) {
    return `${fieldSchema.title || fieldKey}必须是预设选项之一`
  }

  return ''
}

function getConfirmTitle(action: ConfirmAction): string {
  if (action === 'reset') return '确认重置默认配置'
  if (action === 'export') return '确认导出配置'
  if (action === 'import') return '确认导入并覆盖配置'
  return '确认操作'
}

function getConfirmMessage(action: ConfirmAction): string {
  if (action === 'reset') return '重置后会覆盖当前配置并写入 config.json，是否继续？'
  if (action === 'export') return '将导出当前生效配置为 JSON 文件，是否继续？'
  if (action === 'import') return '导入后会覆盖当前配置，并保存到 config.json，是否继续？'
  return '是否继续执行该操作？'
}

function downloadConfigAsFile(config: FormValue, pluginName: string): void {
  const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${pluginName}-config.json`
  anchor.click()
  URL.revokeObjectURL(url)
}

export default PluginConfigPage
