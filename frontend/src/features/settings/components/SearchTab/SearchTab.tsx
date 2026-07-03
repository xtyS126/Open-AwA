/**
 * 搜索配置展示组件
 * 提供 Provider 单选、SearXNG 实例信息录入、连通性测试与保存能力。
 *
 * 设计要点：
 *   - 纯展示组件，所有数据获取与副作用由 SearchTabContainer 注入；
 *   - 表单状态由本组件内部管理，通过 useEffect 与 config prop 同步；
 *   - 使用 zod 在保存前校验 base_url 格式；
 *   - 所有交互元素带 aria-label，错误/结果区域 aria-live="polite"；
 *   - React.memo 包装，避免 Container 重渲染时被动重渲染。
 */
import { memo, useCallback, useEffect, useMemo, useState } from 'react'
import { Eye, EyeOff, Search, Save, Play, AlertTriangle, Check, Server, Ban } from 'lucide-react'
import { z } from 'zod'
import type {
  SearchConfig,
  SearchConfigTest,
  SearchConfigUpdate,
  SearchProvider,
  SearchTestResult,
} from '@/shared/api/searchConfigApi'
import { Button } from '@/shared/components/ui/Button'
import { Toggle } from '@/shared/components/ui/Toggle'
import styles from './SearchTab.module.css'

/** 表单状态：与后端 SearchConfig 对齐，但允许 base_url / api_key 为本地编辑值 */
interface SearchFormState {
  provider: SearchProvider
  baseUrl: string
  apiKey: string
  allowPrivateNetwork: boolean
}

/** 默认表单状态：与 spec 一致，provider 默认 searxng */
const DEFAULT_FORM_STATE: SearchFormState = {
  provider: 'searxng',
  baseUrl: 'http://192.168.2.10:7653/',
  apiKey: '',
  allowPrivateNetwork: false,
}

/** SearXNG base_url 校验 schema */
const baseUrlSchema = z
  .string()
  .min(1, '请填写 SearXNG 实例地址')
  .refine((value) => value.startsWith('http://') || value.startsWith('https://'), {
    message: '地址必须以 http:// 或 https:// 开头',
  })

/** Provider 单选项配置 */
interface ProviderOption {
  id: SearchProvider
  label: string
  description: string
  icon: typeof Search
}

const PROVIDER_OPTIONS: readonly ProviderOption[] = [
  {
    id: 'searxng',
    label: 'SearXNG（自建实例）',
    description: '连接到自建或私有的 SearXNG 实例',
    icon: Server,
  },
  {
    id: 'duckduckgo',
    label: 'DuckDuckGo（内置默认）',
    description: '使用内置 DuckDuckGo HTML 接口，无需配置',
    icon: Search,
  },
  {
    id: 'disabled',
    label: '禁用搜索',
    description: '关闭网络搜索能力',
    icon: Ban,
  },
] as const

/** 私有 IP 网段前缀，用于判断 base_url 是否指向内网 */
const PRIVATE_IP_PREFIXES: readonly string[] = [
  '192.168.',
  '10.',
  '172.16.',
  '172.17.',
  '172.18.',
  '172.19.',
  '172.20.',
  '172.21.',
  '172.22.',
  '172.23.',
  '172.24.',
  '172.25.',
  '172.26.',
  '172.27.',
  '172.28.',
  '172.29.',
  '172.30.',
  '172.31.',
  '127.',
  'localhost',
] as const

/** 判断给定 base_url 是否指向私有 IP / localhost */
function isPrivateNetworkUrl(baseUrl: string): boolean {
  const trimmed = baseUrl.trim().toLowerCase()
  if (!trimmed) return false
  // 从 http(s):// 后提取 host 段
  const match = trimmed.match(/^https?:\/\/([^/:]+)/)
  if (!match) return false
  const host = match[1]
  return PRIVATE_IP_PREFIXES.some((prefix) => host.startsWith(prefix))
}

interface SearchTabProps {
  /** 当前激活的搜索配置，初次加载时为 null */
  config: SearchConfig | null
  /** 是否正在加载配置 */
  isLoading: boolean
  /** 加载错误信息 */
  error: string | null
  /** 保存配置回调，由 Container 处理实际 API 调用与 Toast */
  onSave: (config: SearchConfigUpdate) => Promise<void>
  /** 测试连通性回调，由 Container 处理实际 API 调用 */
  onTest: (config: SearchConfigTest) => Promise<SearchTestResult>
}

function SearchTabImpl({
  config,
  isLoading,
  error,
  onSave,
  onTest,
}: SearchTabProps) {
  // 表单状态：从 config prop 同步初始值，用户编辑后由本地 state 接管
  const [formState, setFormState] = useState<SearchFormState>(DEFAULT_FORM_STATE)
  const [showApiKey, setShowApiKey] = useState<boolean>(false)
  const [testing, setTesting] = useState<boolean>(false)
  const [saving, setSaving] = useState<boolean>(false)
  const [testResult, setTestResult] = useState<SearchTestResult | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [testError, setTestError] = useState<string | null>(null)

  // 配置加载完成后，将后端值同步到本地表单状态
  // 仅在 config 引用变化时同步，避免覆盖用户编辑
  useEffect(() => {
    if (!config) return
    setFormState({
      provider: config.provider,
      baseUrl: config.base_url ?? DEFAULT_FORM_STATE.baseUrl,
      apiKey: '',
      allowPrivateNetwork: Boolean(config.extra_config?.allow_private_network),
    })
    // 加载新配置时清空测试结果与错误
    setTestResult(null)
    setTestError(null)
    setFormError(null)
  }, [config])

  /** 当前 base_url 是否指向私有 IP（仅 searxng 模式下需要展示开关） */
  const isPrivateNetwork = useMemo(() => {
    if (formState.provider !== 'searxng') return false
    return isPrivateNetworkUrl(formState.baseUrl)
  }, [formState.provider, formState.baseUrl])

  /** 当前表单的 base_url 校验错误（用于输入框红框提示） */
  const baseUrlValidationError = useMemo(() => {
    if (formState.provider !== 'searxng') return null
    const result = baseUrlSchema.safeParse(formState.baseUrl)
    return result.success ? null : result.error.issues[0]?.message ?? null
  }, [formState.provider, formState.baseUrl])

  /** provider 切换回调 */
  const handleProviderChange = useCallback((provider: SearchProvider) => {
    setFormState((prev) => ({ ...prev, provider }))
    // 切换 provider 时清空测试结果与错误
    setTestResult(null)
    setTestError(null)
    setFormError(null)
  }, [])

  /** base_url 输入变更 */
  const handleBaseUrlChange = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const value = event.target.value
    setFormState((prev) => ({ ...prev, baseUrl: value }))
  }, [])

  /** API Key 输入变更 */
  const handleApiKeyChange = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const value = event.target.value
    setFormState((prev) => ({ ...prev, apiKey: value }))
  }, [])

  /** allow_private_network 开关变更 */
  const handleAllowPrivateNetworkChange = useCallback((checked: boolean) => {
    setFormState((prev) => ({ ...prev, allowPrivateNetwork: checked }))
  }, [])

  /** 构造测试连通性请求体（disabled 时禁用按钮，不会进入此分支） */
  const buildTestPayload = useCallback((): SearchConfigTest | null => {
    if (formState.provider === 'disabled') return null
    return {
      provider: formState.provider,
      base_url: formState.provider === 'searxng' ? formState.baseUrl.trim() : undefined,
      api_key: formState.provider === 'searxng' && formState.apiKey.trim()
        ? formState.apiKey.trim()
        : undefined,
      extra_config: { allow_private_network: formState.allowPrivateNetwork },
    }
  }, [formState])

  /** 点击测试连通性按钮 */
  const handleTest = useCallback(async () => {
    if (testing || saving) return
    // 校验 base_url
    if (formState.provider === 'searxng') {
      const result = baseUrlSchema.safeParse(formState.baseUrl)
      if (!result.success) {
        const message = result.error.issues[0]?.message ?? 'URL 格式无效'
        setFormError(message)
        setTestError(message)
        return
      }
    }
    const payload = buildTestPayload()
    if (!payload) return

    setTesting(true)
    setTestResult(null)
    setTestError(null)
    setFormError(null)
    try {
      const result = await onTest(payload)
      setTestResult(result)
    } catch (err) {
      const message = err instanceof Error ? err.message : '测试请求失败'
      setTestError(message)
    } finally {
      setTesting(false)
    }
  }, [testing, saving, formState, buildTestPayload, onTest])

  /** 点击保存按钮 */
  const handleSave = useCallback(async () => {
    if (testing || saving) return
    // 校验 base_url（searxng 模式下）
    if (formState.provider === 'searxng') {
      const result = baseUrlSchema.safeParse(formState.baseUrl)
      if (!result.success) {
        const message = result.error.issues[0]?.message ?? 'URL 格式无效'
        setFormError(message)
        return
      }
    }

    const payload: SearchConfigUpdate = {
      provider: formState.provider,
      base_url: formState.provider === 'searxng' ? formState.baseUrl.trim() : null,
      api_key: formState.provider === 'searxng' && formState.apiKey.trim()
        ? formState.apiKey.trim()
        : undefined,
      enabled: true,
      extra_config: { allow_private_network: formState.allowPrivateNetwork },
    }

    setSaving(true)
    setFormError(null)
    try {
      await onSave(payload)
    } catch (err) {
      const message = err instanceof Error ? err.message : '保存失败'
      setFormError(message)
    } finally {
      setSaving(false)
    }
  }, [testing, saving, formState, onSave])

  /** 渲染顶部加载态 */
  if (isLoading) {
    return (
      <div className={styles.container} role="status" aria-live="polite">
        <div className={styles.header}>
          <h2 className={styles.title}>搜索配置</h2>
          <p className={styles.subtitle}>配置网络搜索后端</p>
        </div>
        <div className={styles.loading}>正在加载配置...</div>
      </div>
    )
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h2 className={styles.title}>搜索配置</h2>
        <p className={styles.subtitle}>配置网络搜索后端</p>
      </div>

      {/* 加载错误提示（来自 Container 层） */}
      {error && (
        <div className={styles.errorBanner} role="alert" aria-live="polite">
          <AlertTriangle size={14} aria-hidden="true" /> {error}
        </div>
      )}

      {/* 表单内错误提示（base_url 校验失败、保存失败等） */}
      {formError && !error && (
        <div className={styles.errorBanner} role="alert" aria-live="polite">
          <AlertTriangle size={14} aria-hidden="true" /> {formError}
        </div>
      )}

      {/* Provider 单选按钮组 */}
      <div className={styles.field} role="radiogroup" aria-label="搜索引擎选择">
        <span className={styles.label}>搜索引擎</span>
        <div className={styles.providerGroup}>
          {PROVIDER_OPTIONS.map((option) => {
            const selected = formState.provider === option.id
            const Icon = option.icon
            return (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={selected}
                aria-label={option.label}
                className={[
                  styles.providerOption,
                  selected ? styles.providerOptionSelected : '',
                ].filter(Boolean).join(' ')}
                onClick={() => handleProviderChange(option.id)}
                disabled={testing || saving}
              >
                <input
                  type="radio"
                  name="search-provider"
                  value={option.id}
                  checked={selected}
                  readOnly
                  className={styles.providerRadio}
                  aria-hidden="true"
                  tabIndex={-1}
                />
                <span className={styles.providerContent}>
                  <span className={styles.providerTitle}>
                    <Icon size={14} aria-hidden="true" />
                    {option.label}
                  </span>
                  <span className={styles.providerDesc}>{option.description}</span>
                </span>
              </button>
            )
          })}
        </div>
      </div>

      {/* SearXNG 专属字段：仅在 provider=searxng 时展示 */}
      {formState.provider === 'searxng' && (
        <>
          {/* base_url 输入框 */}
          <div className={styles.field}>
            <label className={styles.label} htmlFor="search-base-url">
              Base URL
            </label>
            <input
              id="search-base-url"
              type="text"
              className={[
                styles.input,
                baseUrlValidationError ? styles.inputInvalid : '',
              ].filter(Boolean).join(' ')}
              value={formState.baseUrl}
              onChange={handleBaseUrlChange}
              placeholder="http://192.168.2.10:7653/"
              disabled={testing || saving}
              aria-invalid={Boolean(baseUrlValidationError)}
              aria-describedby="search-base-url-help"
              autoComplete="off"
              spellCheck={false}
            />
            <span id="search-base-url-help" className={styles.helperText}>
              SearXNG 实例地址，必须以 http:// 或 https:// 开头
            </span>
          </div>

          {/* API Key 密码框 */}
          <div className={styles.field}>
            <label className={styles.label} htmlFor="search-api-key">
              API Key
              {/* 后端已配置 api_key 时显示徽章 */}
              {config?.api_key_set ? (
                <span
                  className={`${styles.apiKeyBadge} ${styles.apiKeyBadgeSet}`}
                  aria-label="API Key 已设置"
                >
                  <Check size={11} aria-hidden="true" /> 已设置
                </span>
              ) : (
                <span
                  className={`${styles.apiKeyBadge} ${styles.apiKeyBadgeNotSet}`}
                  aria-label="API Key 未设置"
                >
                  未设置
                </span>
              )}
            </label>
            <div className={styles.inputRow}>
              <input
                id="search-api-key"
                type={showApiKey ? 'text' : 'password'}
                className={styles.input}
                value={formState.apiKey}
                onChange={handleApiKeyChange}
                placeholder="可选，部分 SearXNG 实例需要鉴权"
                disabled={testing || saving}
                autoComplete="new-password"
                spellCheck={false}
              />
              <button
                type="button"
                className={styles.toggleButton}
                onClick={() => setShowApiKey((prev) => !prev)}
                disabled={testing || saving}
                aria-label={showApiKey ? '隐藏 API Key' : '显示 API Key'}
                aria-pressed={showApiKey}
              >
                {showApiKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
            <span className={styles.helperText}>
              留空表示不修改已保存的 API Key
            </span>
          </div>

          {/* allow_private_network 开关：仅 base_url 为私有 IP 时展示 */}
          {isPrivateNetwork && (
            <div className={styles.toggleRow} role="group" aria-label="内网访问授权">
              <div className={styles.toggleRowContent}>
                <span className={styles.toggleRowLabel}>允许内网访问</span>
                <span className={styles.toggleRowHelp}>
                  启用后可配置 192.168.x.x 等私有 IP，请确保你信任该地址
                </span>
              </div>
              <Toggle
                checked={formState.allowPrivateNetwork}
                onChange={handleAllowPrivateNetworkChange}
                disabled={testing || saving}
                aria-label="允许内网访问"
              />
            </div>
          )}
        </>
      )}

      {/* 测试结果展示 */}
      {(testResult || testError) && (
        <div
          className={[
            styles.testResult,
            testResult?.success ? styles.testResultSuccess : styles.testResultFailure,
          ].filter(Boolean).join(' ')}
          role="status"
          aria-live="polite"
        >
          {testResult ? (
            <>
              <div className={styles.testResultHeader}>
                <span className={styles.testResultTitle}>
                  {testResult.success ? (
                    <>
                      <Check size={14} aria-hidden="true" /> 测试成功
                    </>
                  ) : (
                    <>
                      <AlertTriangle size={14} aria-hidden="true" /> 测试失败
                    </>
                  )}
                </span>
                <span className={styles.testResultMeta}>
                  <span className={styles.testResultMetaItem}>
                    延迟 {testResult.latency_ms}ms
                  </span>
                  {testResult.success && (
                    <span className={styles.testResultMetaItem}>
                      {testResult.sample_results.length} 条样本结果
                    </span>
                  )}
                </span>
              </div>
              {!testResult.success && testResult.error && (
                <div className={styles.testResultMeta}>{testResult.error}</div>
              )}
              {testResult.success && testResult.sample_results.length > 0 && (
                <ul className={styles.sampleList}>
                  {testResult.sample_results.map((item, index) => (
                    <li key={`${item.url}-${index}`} className={styles.sampleItem}>
                      <span className={styles.sampleItemTitle}>
                        {item.title || '(无标题)'}
                      </span>
                      <span className={styles.sampleItemUrl}>{item.url}</span>
                      {item.snippet && (
                        <span className={styles.sampleItemSnippet}>{item.snippet}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <div className={styles.testResultHeader}>
              <span className={styles.testResultTitle}>
                <AlertTriangle size={14} aria-hidden="true" /> 测试失败
              </span>
              <span className={styles.testResultMeta}>{testError}</span>
            </div>
          )}
        </div>
      )}

      {/* 操作按钮 */}
      <div className={styles.actions}>
        <Button
          variant="secondary"
          size="md"
          onClick={handleTest}
          loading={testing}
          disabled={
            saving
            || formState.provider === 'disabled'
            || Boolean(baseUrlValidationError)
          }
          aria-label="测试连通性"
        >
          {!testing && <Play size={14} aria-hidden="true" />}
          {testing ? '测试中...' : '测试连通性'}
        </Button>
        <Button
          variant="primary"
          size="md"
          onClick={handleSave}
          loading={saving}
          disabled={testing || Boolean(baseUrlValidationError)}
          aria-label="保存配置"
        >
          {!saving && <Save size={14} aria-hidden="true" />}
          {saving ? '保存中...' : '保存'}
        </Button>
      </div>
    </div>
  )
}

/**
 * 使用 React.memo 优化纯展示组件的重渲染。
 * 仅在 props（config / isLoading / error / 回调引用）变化时重渲染。
 * 由于 Container 使用 useCallback 包装回调，本组件可稳定避免不必要的重渲染。
 */
export const SearchTab = memo(SearchTabImpl)
export type { SearchTabProps }
