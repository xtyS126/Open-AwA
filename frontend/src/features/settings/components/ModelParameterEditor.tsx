/**
 * 模型参数编辑器组件，提供 7 个可调参数的滑块/数字输入。
 * 纯展示组件，所有状态由父组件通过 props 传入。
 */
import styles from '@/features/settings/SettingsPage.module.css'

/** 模型可编辑参数的接口定义 */
export interface ModelEditParams {
  temperature: number
  top_p: number
  max_tokens: number
  frequency_penalty: number
  presence_penalty: number
  timeout: number
  retry_count: number
}

/** 模型参数的默认值 */
export const MODEL_PARAM_DEFAULTS: ModelEditParams = {
  temperature: 0.7,
  top_p: 0.9,
  max_tokens: 0,        // 0 表示"使用模型默认上限"
  frequency_penalty: 0.0,
  presence_penalty: 0.0,
  timeout: 120,
  retry_count: 3,
}

interface ModelParameterEditorProps {
  /** 当前参数值 */
  params: ModelEditParams
  /** 参数变更回调，field 为参数名，value 为新值 */
  onChange: (field: keyof ModelEditParams, value: number) => void
  /** 是否为只读模式（保存中时禁用编辑） */
  disabled?: boolean
}

export function ModelParameterEditor({ params, onChange, disabled = false }: ModelParameterEditorProps) {
  /**
   * 处理数字输入清空：恢复默认值。
   * 确保清空输入框时不会将非法值（如 0）发送给后端。
   */
  const handleNumberClear = (field: keyof ModelEditParams) => {
    onChange(field, MODEL_PARAM_DEFAULTS[field])
  }

  return (
    <div className={styles['model-config-params-grid']}>
      {/* 温度 Temperature */}
      <div className={styles['form-group']}>
        <label>温度 (Temperature): {params.temperature.toFixed(1)}</label>
        <div className={styles['slider-row']}>
          <input
            type="range"
            min={0}
            max={2}
            step={0.1}
            value={params.temperature}
            onChange={(e) => onChange('temperature', parseFloat(e.target.value))}
            className={styles['param-slider']}
            disabled={disabled}
          />
          <input
            type="number"
            min={0}
            max={2}
            step={0.1}
            value={params.temperature}
            onChange={(e) => {
              const val = parseFloat(e.target.value)
              if (!isNaN(val) && val >= 0 && val <= 2) onChange('temperature', val)
            }}
            className={styles['param-number-input']}
            disabled={disabled}
          />
        </div>
      </div>

      {/* Top P */}
      <div className={styles['form-group']}>
        <label>Top P: {params.top_p.toFixed(2)}</label>
        <div className={styles['slider-row']}>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={params.top_p}
            onChange={(e) => onChange('top_p', parseFloat(e.target.value))}
            className={styles['param-slider']}
            disabled={disabled}
          />
          <input
            type="number"
            min={0}
            max={1}
            step={0.05}
            value={params.top_p}
            onChange={(e) => {
              const val = parseFloat(e.target.value)
              if (!isNaN(val) && val >= 0 && val <= 1) onChange('top_p', val)
            }}
            className={styles['param-number-input']}
            disabled={disabled}
          />
        </div>
      </div>

      {/* 最大 Tokens */}
      <div className={styles['form-group']}>
        <label>最大 Tokens</label>
        <input
          type="number"
          min={0}
          step={1}
          value={params.max_tokens || ''}
          onChange={(e) => {
            const val = e.target.value
            if (val === '') {
              handleNumberClear('max_tokens')
            } else {
              const parsed = parseInt(val, 10)
              if (!isNaN(parsed) && parsed > 0) onChange('max_tokens', parsed)
            }
          }}
          placeholder="默认使用模型上限"
          className={styles['param-number-input']}
          disabled={disabled}
        />
        <span className={styles['param-hint']}>留空表示使用当前模型的默认限制</span>
      </div>

      {/* 频率惩罚 Frequency Penalty */}
      <div className={styles['form-group']}>
        <label>频率惩罚 (Frequency Penalty): {params.frequency_penalty.toFixed(1)}</label>
        <div className={styles['slider-row']}>
          <input
            type="range"
            min={-2}
            max={2}
            step={0.1}
            value={params.frequency_penalty}
            onChange={(e) => onChange('frequency_penalty', parseFloat(e.target.value))}
            className={styles['param-slider']}
            disabled={disabled}
          />
          <input
            type="number"
            min={-2}
            max={2}
            step={0.1}
            value={params.frequency_penalty}
            onChange={(e) => {
              const val = parseFloat(e.target.value)
              if (!isNaN(val) && val >= -2 && val <= 2) onChange('frequency_penalty', val)
            }}
            className={styles['param-number-input']}
            disabled={disabled}
          />
        </div>
        <span className={styles['param-hint']}>正值减少重复，负值增加多样性</span>
      </div>

      {/* 存在惩罚 Presence Penalty */}
      <div className={styles['form-group']}>
        <label>存在惩罚 (Presence Penalty): {params.presence_penalty.toFixed(1)}</label>
        <div className={styles['slider-row']}>
          <input
            type="range"
            min={-2}
            max={2}
            step={0.1}
            value={params.presence_penalty}
            onChange={(e) => onChange('presence_penalty', parseFloat(e.target.value))}
            className={styles['param-slider']}
            disabled={disabled}
          />
          <input
            type="number"
            min={-2}
            max={2}
            step={0.1}
            value={params.presence_penalty}
            onChange={(e) => {
              const val = parseFloat(e.target.value)
              if (!isNaN(val) && val >= -2 && val <= 2) onChange('presence_penalty', val)
            }}
            className={styles['param-number-input']}
            disabled={disabled}
          />
        </div>
        <span className={styles['param-hint']}>正值鼓励讨论新话题，负值允许重复</span>
      </div>

      {/* 超时时间 */}
      <div className={styles['form-group']}>
        <label>超时时间（秒）</label>
        <input
          type="number"
          min={1}
          max={600}
          step={1}
          value={params.timeout || ''}
          onChange={(e) => {
            const val = e.target.value
            if (val === '') {
              handleNumberClear('timeout')
            } else {
              const parsed = parseInt(val, 10)
              if (!isNaN(parsed) && parsed >= 1 && parsed <= 600) onChange('timeout', parsed)
            }
          }}
          placeholder="120"
          className={styles['param-number-input']}
          disabled={disabled}
        />
        <span className={styles['param-hint']}>API 调用超时上限，范围 1-600 秒</span>
      </div>

      {/* 重试次数 */}
      <div className={styles['form-group']}>
        <label>重试次数</label>
        <input
          type="number"
          min={0}
          max={10}
          step={1}
          value={params.retry_count ?? ''}
          onChange={(e) => {
            const val = e.target.value
            if (val === '') {
              handleNumberClear('retry_count')
            } else {
              const parsed = parseInt(val, 10)
              if (!isNaN(parsed) && parsed >= 0 && parsed <= 10) onChange('retry_count', parsed)
            }
          }}
          placeholder="3"
          className={styles['param-number-input']}
          disabled={disabled}
        />
        <span className={styles['param-hint']}>失败后最大重试次数，范围 0-10</span>
      </div>
    </div>
  )
}

export default ModelParameterEditor
