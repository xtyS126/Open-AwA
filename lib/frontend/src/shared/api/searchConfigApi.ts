/**
 * 搜索配置 API 模块。
 * 封装 /api/search 端点的 GET / PUT / POST 接口，
 * 提供搜索 Provider 配置的查询、更新与连通性测试能力。
 *
 * 类型定义与后端 backend/api/routes/search_config.py 严格对齐：
 *   - SearchConfigResponse: api_key_set / enabled 字段
 *   - SearchTestResponse.sample_results: [{ title, url, snippet }]
 *   - SearchTestRequest.test_query（非 query）
 *   - POST /test 仅接受 duckduckgo / searxng，不接受 disabled
 */
import api from '@/shared/api/api'

/** 搜索 Provider 类型，与配置项一致 */
export type SearchProvider = 'duckduckgo' | 'searxng' | 'disabled'

/**
 * 测试连通性允许的 Provider 类型。
 * 后端 POST /api/search/test 校验 provider 仅接受 duckduckgo / searxng，
 * disabled 无法测试连通性。
 */
export type SearchTestProvider = 'duckduckgo' | 'searxng'

/** Provider 额外配置，目前仅支持内网访问开关 */
export interface SearchExtraConfig {
  /** 是否允许配置 192.168.x.x 等私有 IP（仅 searxng 生效） */
  allow_private_network?: boolean
}

/** GET /api/search/config 响应体 */
export interface SearchConfig {
  /** 当前激活的 provider */
  provider: SearchProvider
  /** SearXNG 实例地址，duckduckgo / disabled 时为 null */
  base_url: string | null
  /** API Key 是否已设置（不暴露原值） */
  api_key_set: boolean
  /** 配置是否启用 */
  enabled: boolean
  /** 额外配置 */
  extra_config: SearchExtraConfig
}

/** PUT /api/search/config 请求体 */
export interface SearchConfigUpdate {
  provider: SearchProvider
  /** 留空表示不修改 base_url */
  base_url?: string | null
  /** 留空表示不修改 api_key */
  api_key?: string
  /** 是否启用，默认 true */
  enabled?: boolean
  extra_config?: SearchExtraConfig
}

/** POST /api/search/test 请求体 */
export interface SearchConfigTest {
  /** 测试连通性仅接受 duckduckgo / searxng */
  provider: SearchTestProvider
  base_url?: string
  api_key?: string
  extra_config?: SearchExtraConfig
  /** 测试查询关键词，默认 openawa */
  test_query?: string
}

/** 单条搜索结果样本 */
export interface SearchResultItem {
  title: string
  url: string
  /** 结果摘要，后端字段为 snippet（非 content） */
  snippet: string
}

/** POST /api/search/test 响应体 */
export interface SearchTestResult {
  success: boolean
  latency_ms: number
  sample_results: SearchResultItem[]
  error?: string
}

/**
 * 获取当前激活的搜索 Provider 配置。
 * 无激活记录时后端返回 duckduckgo 默认值。
 */
export async function getSearchConfig(): Promise<SearchConfig> {
  const response = await api.get<SearchConfig>('/search/config')
  return response.data
}

/**
 * 更新搜索 Provider 配置。
 * 后端会执行 SSRF 校验，私有 IP 且未开启 allow_private_network 时返回 400。
 * @throws {SearchConfigError} 当后端返回 400（SSRF 拒绝 / 校验失败）时抛出携带 detail 的错误
 */
export async function updateSearchConfig(config: SearchConfigUpdate): Promise<SearchConfig> {
  try {
    const response = await api.put<SearchConfig>('/search/config', config)
    return response.data
  } catch (error) {
    // 将后端 detail 信息透传给上层，便于 Container 显示具体错误（如 SSRF 拒绝原因）
    throw normalizeSearchApiError(error)
  }
}

/**
 * 测试搜索 Provider 连通性。
 * 不会写入数据库，仅返回测试结果。
 * @throws {SearchConfigError} 网络错误或后端 422 校验失败时抛出
 */
export async function testSearchConfig(config: SearchConfigTest): Promise<SearchTestResult> {
  try {
    const response = await api.post<SearchTestResult>('/search/test', config)
    return response.data
  } catch (error) {
    throw normalizeSearchApiError(error)
  }
}

/**
 * 标准化后端错误，将 axios 错误转换为携带 detail / status 的 Error 子类。
 * 上层可通过 instanceof SearchConfigError 判断错误来源，
 * 或通过 error.status 区分 400（SSRF 拒绝）与 422（Schema 校验）等情况。
 */
export class SearchConfigError extends Error {
  /** HTTP 状态码 */
  readonly status?: number
  /** 后端返回的具体错误信息（detail 字段） */
  readonly detail: string

  constructor(message: string, detail: string, status?: number) {
    super(message)
    this.name = 'SearchConfigError'
    this.detail = detail
    this.status = status
  }
}

/**
 * 将 axios 错误对象转换为 SearchConfigError。
 * 优先提取后端返回的 detail 字段；若 detail 为数组则拼接为字符串。
 */
function normalizeSearchApiError(error: unknown): SearchConfigError {
  const err = error as {
    response?: { status?: number; data?: { detail?: unknown; error?: unknown } }
    message?: string
  }
  const status = err?.response?.status
  const rawDetail = err?.response?.data?.detail ?? err?.response?.data?.error
  const detail = extractDetail(rawDetail) ?? err?.message ?? '未知错误'
  return new SearchConfigError(detail, detail, status)
}

/** 将后端 detail（可能是 string / array / object）转换为可读字符串 */
function extractDetail(detail: unknown): string | null {
  if (typeof detail === 'string' && detail.trim()) {
    return detail
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object' && 'msg' in item && typeof item.msg === 'string') {
          return item.msg
        }
        return ''
      })
      .filter(Boolean)
    return messages.length > 0 ? messages.join('；') : null
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const msg = (detail as { message: unknown }).message
    if (typeof msg === 'string' && msg.trim()) return msg
  }
  return null
}
