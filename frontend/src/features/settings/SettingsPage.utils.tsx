/**
 * SettingsPage 工具函数模块
 * 从巨型 SettingsPage 中提取的纯函数工具
 */

// ==================== 常量定义 ====================

/** 模态类型枚举 */
export const MODALITY_TYPES = ['text', 'image', 'audio', 'video'] as const

/** 模态类型标签映射 */
export const MODALITY_LABELS: Record<string, string> = {
  text: '文本',
  image: '图片',
  audio: '音频',
  video: '视频',
}

/** 提供商基础路径后缀映射 */
export const PROVIDER_BASE_SUFFIXES: Record<string, string> = {
  openai: '/v1',
  anthropic: '/v1',
  deepseek: '/v1',
  google: '/v1beta',
  alibaba: '/compatible-mode/v1',
  qwen: '/compatible-mode/v1',
  moonshot: '/v1',
  zhipu: '/api/paas/v4',
  ollama: '/v1',
}

/** 提供商预设基础 URL 映射 */
export const PRESET_PROVIDER_BASE_URLS: Record<string, string> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com/v1',
  google: 'https://generativelanguage.googleapis.com/v1beta',
  deepseek: 'https://api.deepseek.com/v1',
  alibaba: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
  moonshot: 'https://api.moonshot.cn/v1',
  zhipu: 'https://open.bigmodel.cn/api/paas/v4',
  ollama: 'http://127.0.0.1:11434/v1',
}

/** 远端模型缓存 TTL（毫秒） */
export const REMOTE_MODEL_CACHE_TTL_MS = 5 * 60 * 1000

/** 模型参数默认值 */
export const MODEL_PARAM_DEFAULTS = {
  temperature: 0.7,
  top_p: 0.9,
  max_tokens: 0,
  frequency_penalty: 0.0,
  presence_penalty: 0.0,
  timeout: 120,
  retry_count: 3,
} as const

// ==================== 纯函数工具 ====================

/**
 * 规范化供应商标识
 * 转为小写，去除空格，替换连续空格为连字符
 */
export function normalizeProviderId(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, '-')
}

/**
 * 获取提供商的基础路径后缀
 */
export function getProviderBaseSuffix(provider: string): string {
  return PROVIDER_BASE_SUFFIXES[normalizeProviderId(provider)] || '/v1'
}

/**
 * 获取供应商的预设基础 URL
 */
export function getPresetProviderBaseUrl(provider: string): string {
  return PRESET_PROVIDER_BASE_URLS[normalizeProviderId(provider)] || ''
}

/**
 * 规范化提供商基础 URL
 * 移除已知的端点后缀，确保以正确的 Base Suffix 结尾
 */
export function normalizeProviderBaseUrl(provider: string, apiEndpoint: string): string {
  let raw = apiEndpoint.trim()
  if (!raw) {
    return ''
  }

  try {
    new URL(raw)
  } catch (e) {
    // 返回原始值，让后端或其他逻辑处理
  }

  const knownSuffixes = [
    '/v1/chat/completions',
    '/compatible-mode/v1/chat/completions',
    '/api/paas/v4/chat/completions',
    '/v1/messages',
    '/v1beta/models',
    '/v1/models',
    '/chat/completions',
    '/models',
  ]

  let trimmed = raw.replace(/\/+$/, '')
  const lowerTrimmed = trimmed.toLowerCase()

  for (const suffix of knownSuffixes) {
    if (lowerTrimmed.endsWith(suffix.toLowerCase())) {
      trimmed = trimmed.slice(0, trimmed.length - suffix.length).replace(/\/+$/, '')
      break
    }
  }

  const baseSuffix = getProviderBaseSuffix(provider)
  if (!trimmed.toLowerCase().endsWith(baseSuffix.toLowerCase())) {
    trimmed = `${trimmed}${baseSuffix}`
  }

  return trimmed
}

/**
 * 构建持久化设置对象
 */
export function buildPersistedSettings(settings: {
  theme: string
  language: string
  apiProvider: string
  requireConfirm: boolean
  enableAudit: boolean
  maxToolCallRounds: number
}): {
  theme: string
  language: string
  apiProvider: string
  requireConfirm: boolean
  enableAudit: boolean
  maxToolCallRounds: number
} {
  return {
    theme: settings.theme,
    language: settings.language,
    apiProvider: settings.apiProvider,
    requireConfirm: settings.requireConfirm,
    enableAudit: settings.enableAudit,
    maxToolCallRounds: settings.maxToolCallRounds,
  }
}

/**
 * 检查是否为有效的持久化设置
 */
export function isPersistedSettings(value: unknown): value is Partial<ReturnType<typeof buildPersistedSettings>> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false
  }

  const candidate = value as Record<string, unknown>
  return (
    (candidate.theme === undefined || typeof candidate.theme === 'string') &&
    (candidate.language === undefined || typeof candidate.language === 'string') &&
    (candidate.apiProvider === undefined || typeof candidate.apiProvider === 'string') &&
    (candidate.requireConfirm === undefined || typeof candidate.requireConfirm === 'boolean') &&
    (candidate.enableAudit === undefined || typeof candidate.enableAudit === 'boolean') &&
    (candidate.maxToolCallRounds === undefined || typeof candidate.maxToolCallRounds === 'number')
  )
}

/**
 * 格式化 token 数量显示
 */
export function formatTokenCount(tokens: number | null | undefined): string {
  if (tokens == null) return '-'
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(0)}K`
  return String(tokens)
}

/**
 * 格式化价格显示
 */
export function formatPrice(price: number, currency: string): string {
  const symbol = currency === 'CNY' ? '¥' : '$'
  return `${symbol}${price.toFixed(4)}`
}

/**
 * 格式化布尔值标签
 */
export function formatBooleanLabel(value: boolean | null | undefined): string {
  return value ? '支持' : '不支持'
}

/**
 * 格式化模型大小
 */
export function formatModelSize(bytes: number): string {
  if (!bytes) return '-'
  if (bytes >= 1073741824) return `${(bytes / 1073741824).toFixed(1)} GB`
  if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(0)} MB`
  return `${(bytes / 1024).toFixed(0)} KB`
}

/**
 * 获取提供商连接状态指示器
 */
export function getStatusIndicator(status: string): { label: string; color: string } {
  switch (status) {
    case 'connected':
      return { label: '已连接', color: '#22c55e' }
    case 'auth_error':
      return { label: '认证失败', color: '#ef4444' }
    case 'timeout':
      return { label: '超时', color: '#f59e0b' }
    case 'unreachable':
      return { label: '不可达', color: '#ef4444' }
    case 'unconfigured':
      return { label: '未配置', color: '#9ca3af' }
    default:
      return { label: '异常', color: '#ef4444' }
  }
}

/**
 * 从配置和能力数据构建模型编辑参数
 */
export function buildModelEditParams(
  config: {
    temperature?: number | null
    top_p?: number | null
    max_tokens_limit?: number | null
    frequency_penalty?: number | null
    presence_penalty?: number | null
    timeout?: number | null
    retry_count?: number | null
  },
  caps?: {
    defaults: {
      temperature: number
      top_k: number
      max_tokens: number
      frequency_penalty: number
      presence_penalty: number
      timeout: number
      retry_count: number
    }
  }
): {
  temperature: number
  top_p: number
  max_tokens: number
  frequency_penalty: number
  presence_penalty: number
  timeout: number
  retry_count: number
} {
  return {
    temperature: config.temperature ?? caps?.defaults?.temperature ?? MODEL_PARAM_DEFAULTS.temperature,
    top_p: config.top_p ?? MODEL_PARAM_DEFAULTS.top_p,
    max_tokens: config.max_tokens_limit ?? caps?.defaults?.max_tokens ?? MODEL_PARAM_DEFAULTS.max_tokens,
    frequency_penalty: config.frequency_penalty ?? caps?.defaults?.frequency_penalty ?? MODEL_PARAM_DEFAULTS.frequency_penalty,
    presence_penalty: config.presence_penalty ?? caps?.defaults?.presence_penalty ?? MODEL_PARAM_DEFAULTS.presence_penalty,
    timeout: config.timeout ?? caps?.defaults?.timeout ?? MODEL_PARAM_DEFAULTS.timeout,
    retry_count: config.retry_count ?? caps?.defaults?.retry_count ?? MODEL_PARAM_DEFAULTS.retry_count,
  }
}

/**
 * 获取模型配置的参数摘要（用于折叠态展示）
 */
export function getModelParamSummary(
  modelName: string,
  configurations: {
    provider: string
    model: string
    temperature?: number | null
    max_tokens_limit?: number | null
  }[]
): string {
  const config = configurations.find(c => c.model === modelName)
  if (!config) return '未配置'
  const temp = config.temperature ?? 0.7
  const maxT = config.max_tokens_limit
  const parts: string[] = [`温度: ${temp.toFixed(1)}`]
  if (maxT) parts.push(`最大 Tokens: ${formatTokenCount(maxT)}`)
  return parts.join(' · ')
}

/**
 * 渲染模态标签
 */
export function renderModalityTags(
  inputModality: string[] | undefined,
  outputModality: string[] | undefined,
  modalityLabels: Record<string, string> = MODALITY_LABELS
): JSX.Element {
  const inputTags = (inputModality?.length ? inputModality : ['text'])
    .map(m => modalityLabels[m] || m)
  const outputTags = (outputModality?.length ? outputModality : ['text'])
    .map(m => modalityLabels[m] || m)

  const inputStr = inputTags.join('+')
  const outputStr = outputTags.join('+')

  return (
    <span className={''}>
      {inputStr} → {outputStr}
    </span>
  )
}

