/**
 * 通用设置组件
 * 包括：主题、语言、工具回环、输出模式、主模型选择、AI参数配置
 */
import { memo, useMemo } from 'react'
import type { ModelConfiguration, ModelCapabilitiesResponse } from '@/features/settings/modelsApi'
import type { ModelPricing } from '@/features/billing/billingApi'
import type { ModelOption } from '@/features/chat/store/chatStore'
import { formatTokenCount } from '@/features/settings/SettingsPage.utils.tsx'
import styles from '@/features/settings/SettingsPage.module.css'

// ConfigModelOption 类型定义
interface ConfigModelOption {
  key: string
  configId: number
  provider: string
  providerDisplayName: string
  modelName: string
  configuration: ModelConfiguration
}

// 注意：Settings 接口与父组件保持一致，包含 apiKey
type Settings = {
  theme: string
  language: string
  apiProvider: string
  apiKey: string
  requireConfirm: boolean
  enableAudit: boolean
  maxToolCallRounds: number
  promptContent: string
}

interface GeneralSettingsProps {
  // 状态
  settings: Settings
  outputMode: 'stream' | 'direct'
  globalSelectedModel: string
  modelOptions: ModelOption[]
  hasAttemptedGlobalModelLoad: boolean
  globalModelLoadSummary: string | null
  modelLoading: boolean
  modelError: string | null
  configurations: ModelConfiguration[]
  selectedConfigModelOptionKey: string
  editingTemperature: number
  editingTopK: number
  editingMaxTokensLimit: number | ''
  modelCapabilities: ModelCapabilitiesResponse | null
  models: ModelPricing[]
  savingModelParams: boolean

  // 回调
  onSettingChange: <K extends keyof Settings>(key: K, value: Settings[K]) => void
  onOutputModeChange: (mode: 'stream' | 'direct') => void
  onGlobalModelChange: (modelId: string) => void
  onLoadGlobalModelOptions: () => void
  onSelectModelConfig: (key: string) => void
  onSaveModelParams: () => void
  onResetModelParams: () => void
  /** 保存通用设置回调（设置页面"保存设置"按钮） */
  onSave: () => void
}

function GeneralSettingsInner({
  settings,
  outputMode,
  globalSelectedModel,
  modelOptions,
  hasAttemptedGlobalModelLoad,
  globalModelLoadSummary,
  modelLoading,
  modelError,
  configurations,
  selectedConfigModelOptionKey,
  editingTemperature,
  editingTopK,
  editingMaxTokensLimit,
  modelCapabilities,
  models,
  savingModelParams,
  onSettingChange,
  onOutputModeChange,
  onGlobalModelChange,
  onLoadGlobalModelOptions,
  onSelectModelConfig,
  onSaveModelParams,
  onResetModelParams,
  onSave,
}: GeneralSettingsProps) {
  // 计算配置模型选项
  const configModelOptions = useMemo<ConfigModelOption[]>(() => {
    return configurations.flatMap((configuration) => {
      const providerDisplayName = configuration.provider
      const candidateModels = configuration.selected_models && configuration.selected_models.length > 0
        ? configuration.selected_models
        : [configuration.model]

      return candidateModels.map((modelName) => ({
        key: `${configuration.id}:${modelName}`,
        configId: configuration.id,
        provider: configuration.provider,
        providerDisplayName,
        modelName,
        configuration,
      }))
    })
  }, [configurations])

  const selectedConfigModelOption = useMemo(
    () => configModelOptions.find((option) => option.key === selectedConfigModelOptionKey) ?? null,
    [configModelOptions, selectedConfigModelOptionKey]
  )

  // 计算计费模型（用于价格显示）
  const selectedBillingModel = useMemo(() => {
    if (!selectedConfigModelOption) {
      return null
    }
    return models.find((model) => (
      model.provider === selectedConfigModelOption.provider &&
      model.model === selectedConfigModelOption.modelName
    )) ?? null
  }, [models, selectedConfigModelOption])

  // 计算 linked 模型容量信息
  const linkedModelMaxTokens = useMemo(() => {
    if (!selectedConfigModelOption) {
      return null
    }

    return (
      selectedConfigModelOption.configuration.max_tokens_limit ??
      selectedConfigModelOption.configuration.model_spec?.max_output_tokens ??
      modelCapabilities?.limits.max_tokens_max ??
      selectedBillingModel?.context_window ??
      null
    )
  }, [modelCapabilities, selectedBillingModel, selectedConfigModelOption])

  const linkedModelContextWindow = useMemo(() => {
    if (!selectedConfigModelOption) {
      return null
    }

    return (
      selectedBillingModel?.context_window ??
      selectedConfigModelOption.configuration.model_spec?.context_window ??
      modelCapabilities?.limits.max_tokens_max ??
      null
    )
  }, [modelCapabilities, selectedBillingModel, selectedConfigModelOption])

  return (
    <div className={styles['settings-section']}>
      <h2>通用设置</h2>
      <div className={styles['setting-item']}>
        <label>主题</label>
        <select
          value={settings.theme}
          onChange={(e) => onSettingChange('theme', e.target.value)}
        >
          <option value="light">浅色</option>
          <option value="dark">深色</option>
        </select>
      </div>
      <div className={styles['setting-item']}>
        <label>语言</label>
        <select
          value={settings.language}
          onChange={(e) => onSettingChange('language', e.target.value)}
        >
          <option value="zh">中文</option>
          <option value="en">English</option>
        </select>
      </div>
      <div className={styles['setting-item']}>
        <label htmlFor="max-tool-call-rounds">工具回环次数上限</label>
        <input
          id="max-tool-call-rounds"
          type="number"
          min={1}
          max={50000}
          step={1}
          value={settings.maxToolCallRounds}
          onChange={(e) => {
            const nextValue = Number.parseInt(e.target.value, 10)
            if (Number.isNaN(nextValue)) {
              return
            }
            onSettingChange('maxToolCallRounds', Math.max(1, Math.min(50000, nextValue)))
          }}
        />
        <span className={styles['param-hint']}>控制单次对话中 AI 连续工具调用的最大轮次，默认 12。</span>
      </div>
      <button
        className={`btn btn-primary`}
        onClick={onSave}
      >
        保存设置
      </button>

      <h2 style={{ marginTop: '32px' }}>主模型选择</h2>
      <p className={styles['section-desc']}>选择聊天页面使用的默认AI模型和输出模式，对全局生效。</p>
      <div className={styles['setting-item']}>
        <label>输出模式</label>
        <select
          value={outputMode}
          onChange={(e) => onOutputModeChange(e.target.value as 'stream' | 'direct')}
        >
          <option value="stream">流式传输</option>
          <option value="direct">直接输出</option>
        </select>
      </div>
      <div className={styles['setting-item']}>
        <label>默认模型</label>
        {!hasAttemptedGlobalModelLoad ? (
          <div className={styles['remote-model-hint']}>
            <span>默认不在进入页面时自动拉取远端模型列表，点击下方按钮后再读取。</span>
            <button className={`btn ${styles['btn-secondary']}`} onClick={onLoadGlobalModelOptions}>
              加载远端模型
            </button>
          </div>
        ) : modelLoading ? (
          <span style={{ color: 'var(--color-text-tertiary)', fontSize: '13px' }}>加载远端模型中...</span>
        ) : modelError ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ color: 'var(--color-danger)', fontSize: '13px' }}>{modelError}</span>
            <button className="btn btn-sm" onClick={onLoadGlobalModelOptions}>重试</button>
          </div>
        ) : modelOptions.length === 0 ? (
          <div className={styles['remote-model-hint']}>
            <span style={{ color: 'var(--color-text-tertiary)', fontSize: '13px' }}>
              {globalModelLoadSummary || '暂无可用远端模型，请先在 API 配置中检查供应商状态。'}
            </span>
            <button className={`btn ${styles['btn-secondary']}`} onClick={onLoadGlobalModelOptions}>
              重新读取
            </button>
          </div>
        ) : (
          <div className={styles['remote-model-picker']}>
            <select
              value={globalSelectedModel}
              onChange={(e) => {
                onGlobalModelChange(e.target.value)
              }}
            >
              {modelOptions.map((opt) => (
                <option key={opt.id} value={opt.id}>{opt.display_name}</option>
              ))}
            </select>
            <button className={`btn ${styles['btn-secondary']}`} onClick={onLoadGlobalModelOptions}>
              重新读取
            </button>
          </div>
        )}
        {hasAttemptedGlobalModelLoad && globalModelLoadSummary && (
          <span className={styles['param-hint']}>{globalModelLoadSummary}</span>
        )}
      </div>

      {/* AI参数配置 */}
      {configurations.length > 0 && (
        <div className={styles['model-param-panel']} style={{ marginTop: '24px' }}>
          <h3>AI参数配置</h3>
          <p className={styles['section-desc']}>为选定模型调整生成参数，影响输出风格和长度。</p>
          <div className={styles['model-param-grid']}>
            <div className={styles['form-group']}>
              <label>配置模型</label>
              <select
                value={selectedConfigModelOptionKey}
                onChange={(e) => {
                  if (e.target.value) {
                    onSelectModelConfig(e.target.value)
                  }
                }}
              >
                <option value="">选择模型</option>
                {configModelOptions.map((option) => (
                  <option key={option.key} value={option.key}>
                    {option.providerDisplayName} / {option.modelName}
                  </option>
                ))}
              </select>
            </div>

            <div className={styles['form-group']}>
              <label>
                温度 (Temperature): {editingTemperature.toFixed(1)}
              </label>
              <div className={styles['slider-row']}>
                <input
                  type="range"
                  min={0}
                  max={2}
                  step={0.1}
                  value={editingTemperature}
                  onChange={() => {}} // 状态在父组件
                  disabled={!selectedConfigModelOption || modelCapabilities?.capabilities.supports_temperature === false}
                  className={styles['param-slider']}
                />
                <input
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={editingTemperature}
                  onChange={() => {}} // 状态在父组件
                  disabled={!selectedConfigModelOption || modelCapabilities?.capabilities.supports_temperature === false}
                  className={styles['param-number-input']}
                />
              </div>
              {modelCapabilities?.capabilities.supports_temperature === false && (
                <span className={styles['param-hint']}>该模型不支持温度调节</span>
              )}
            </div>

            <div className={styles['form-group']}>
              <label>Top K / Top P</label>
              <input
                type="number"
                min={0}
                max={1}
                step={0.1}
                value={editingTopK}
                onChange={() => {}} // 状态在父组件
                disabled={!selectedConfigModelOption || modelCapabilities?.capabilities.supports_top_k === false}
                className={styles['param-number-input']}
              />
              {modelCapabilities?.capabilities.supports_top_k === false && (
                <span className={styles['param-hint']}>该模型不支持 Top K / Top P 调节</span>
              )}
            </div>

            <div className={styles['form-group']}>
              <label>最大 Tokens (可选)</label>
              <input
                type="number"
                min={1}
                step={1}
                value={editingMaxTokensLimit === '' ? '' : editingMaxTokensLimit}
                onChange={() => {}} // 状态在父组件
                placeholder="默认使用模型上限"
                disabled={!selectedConfigModelOption}
                className={styles['param-number-input']}
              />
              <span className={styles['param-hint']}>留空表示使用当前模型的默认限制</span>
            </div>
          </div>

          <div className={styles['model-detail-card']}>
            <h4>当前模型详情</h4>
            {!selectedConfigModelOption ? (
              <div className={styles['model-detail-empty']}>
                请选择模型后查看计费配置详情。
              </div>
            ) : (
              <>
                <div className={styles['model-detail-grid']}>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>供应商</span>
                    <span>{selectedConfigModelOption.providerDisplayName}</span>
                  </div>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>模型名称</span>
                    <span>{selectedConfigModelOption.modelName}</span>
                  </div>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>当前最大 Tokens</span>
                    <span>{formatTokenCount(linkedModelMaxTokens)}</span>
                  </div>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>上下文窗口</span>
                    <span>{formatTokenCount(linkedModelContextWindow)}</span>
                  </div>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>输入价格</span>
                    <span>
                      {selectedBillingModel ? formatTokenCount(selectedBillingModel.input_price) : '-'}
                      {selectedBillingModel?.currency}
                    </span>
                  </div>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>输出价格</span>
                    <span>
                      {selectedBillingModel ? formatTokenCount(selectedBillingModel.output_price) : '-'}
                      {selectedBillingModel?.currency}
                    </span>
                  </div>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>缓存价格</span>
                    <span>
                      {selectedBillingModel?.cache_hit_price != null
                        ? formatTokenCount(selectedBillingModel.cache_hit_price) + selectedBillingModel.currency
                        : '-'}
                    </span>
                  </div>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>计费币种</span>
                    <span>{selectedBillingModel?.currency || '-'}</span>
                  </div>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>视觉能力</span>
                    <span>
                      {selectedConfigModelOption.configuration.supports_vision ? '支持' : '不支持'}
                    </span>
                  </div>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>多模态</span>
                    <span>
                      {selectedConfigModelOption.configuration.is_multimodal ? '支持' : '不支持'}
                    </span>
                  </div>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>函数调用</span>
                    <span>
                      {selectedConfigModelOption.configuration.model_spec?.supports_function_calling ?? '未知'}
                    </span>
                  </div>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>流式输出</span>
                    <span>
                      {selectedConfigModelOption.configuration.model_spec?.supports_streaming ?? '未知'}
                    </span>
                  </div>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>状态</span>
                    <span>{selectedConfigModelOption.configuration.status || 'active'}</span>
                  </div>
                  <div className={styles['model-detail-item']}>
                    <span className={styles['model-detail-label']}>更新时间</span>
                    <span>
                      {selectedConfigModelOption.configuration.updated_at
                        ? new Date(selectedConfigModelOption.configuration.updated_at).toLocaleString('zh-CN')
                        : '-'}
                    </span>
                  </div>
                </div>
                {!selectedBillingModel && (
                  <div className={`${styles['message']} ${styles['error']}`} style={{ marginTop: '16px', marginBottom: 0 }}>
                    当前模型未在计费模型表中找到对应详情，已仅展示模型配置与能力信息。
                  </div>
                )}
              </>
            )}
          </div>

          <div className={styles['model-param-actions']}>
            <button
              className={`btn btn-primary`}
              onClick={onSaveModelParams}
              disabled={!selectedConfigModelOption || savingModelParams}
            >
              {savingModelParams ? '保存中...' : '保存参数'}
            </button>
            <button
              className={`btn ${styles['btn-secondary']}`}
              onClick={onResetModelParams}
              disabled={!selectedConfigModelOption || savingModelParams}
            >
              重置为默认
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export const GeneralSettings = memo(GeneralSettingsInner)
export default GeneralSettings
