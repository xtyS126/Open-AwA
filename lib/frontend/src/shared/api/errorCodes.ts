/**
 * 前端镜像错误码常量与辅助函数。
 *
 * 与后端 lib/backend/core/error_codes.py 保持同步：
 * - 错误码字符串必须与后端 ErrorCode 类常量逐字一致
 * - 重试决策与状态码映射优先消费后端返回的 error.code / error.retryable 字段
 * - 后端未返回 code 时回退到字符串匹配 message 的旧逻辑（向后兼容）
 *
 * 修改本文件时必须同步修改后端 error_codes.py，否则前后端契约不一致。
 */

/**
 * 错误码常量。字符串值与后端 core/error_codes.py 的 ErrorCode 类一一对应。
 */
export const ErrorCode = {
  // 通用
  INTERNAL_SERVER_ERROR: 'internal_server_error',
  UNKNOWN_ERROR: 'unknown_error',
  // 网络与超时
  REQUEST_TIMEOUT: 'request_timeout',
  NETWORK_ERROR: 'network_error',
  // 数据库
  DATABASE_UNAVAILABLE: 'database_unavailable',
  // 认证与授权
  UNAUTHORIZED: 'unauthorized',
  FORBIDDEN: 'forbidden',
  AUTHENTICATION_FAILED: 'authentication_failed',
  CSRF_TOKEN_INVALID: 'csrf_token_invalid',
  // LLM
  LLM_API_KEY_STALE: 'llm_api_key_stale',
  LLM_RATE_LIMITED: 'llm_rate_limited',
  LLM_PROVIDER_UNAVAILABLE: 'llm_provider_unavailable',
  LLM_CONTEXT_LENGTH_EXCEEDED: 'llm_context_length_exceeded',
  LLM_CALL_FAILED: 'llm_call_failed',
  // 故障转移
  FAILOVER_TOTAL_TIMEOUT: 'failover_total_timeout',
  FAILOVER_ALL_CANDIDATES_FAILED: 'failover_all_candidates_failed',
  // 系统初始化
  SYSTEM_ALREADY_INITIALIZED: 'system_already_initialized',
  WEAK_PASSWORD: 'weak_password',
  PREREQUISITE_FAILED: 'prerequisite_failed',
  INIT_LOCK_CONTENTION: 'init_lock_contention',
  // 资源不存在
  RESOURCE_NOT_FOUND: 'resource_not_found',
  CONVERSATION_NOT_FOUND: 'conversation_not_found',
  // 输入校验
  VALIDATION_ERROR: 'validation_error',
  INVALID_INPUT: 'invalid_input',
  // 限流
  RATE_LIMIT_EXCEEDED: 'rate_limit_exceeded',
} as const

export type ErrorCodeValue = typeof ErrorCode[keyof typeof ErrorCode]

/**
 * 错误码元信息（与后端 REGISTRY 一致）。
 * 用于在前端独立决策重试与展示，避免每次都向后端确认。
 */
interface ErrorCodeMeta {
  retryable: boolean
  statusCode: number
  userMessage: string
}

const REGISTRY: Record<string, ErrorCodeMeta> = {
  [ErrorCode.INTERNAL_SERVER_ERROR]: { retryable: false, statusCode: 500, userMessage: '服务器内部错误，请稍后重试' },
  [ErrorCode.UNKNOWN_ERROR]: { retryable: false, statusCode: 500, userMessage: '未知错误' },
  [ErrorCode.REQUEST_TIMEOUT]: { retryable: true, statusCode: 504, userMessage: '请求处理超时，请稍后重试' },
  [ErrorCode.NETWORK_ERROR]: { retryable: true, statusCode: 503, userMessage: '网络连接失败，请检查网络后重试' },
  [ErrorCode.DATABASE_UNAVAILABLE]: { retryable: true, statusCode: 503, userMessage: '数据服务暂不可用，请稍后重试' },
  [ErrorCode.UNAUTHORIZED]: { retryable: false, statusCode: 401, userMessage: '未登录或会话已过期' },
  [ErrorCode.FORBIDDEN]: { retryable: false, statusCode: 403, userMessage: '无权访问该资源' },
  [ErrorCode.AUTHENTICATION_FAILED]: { retryable: false, statusCode: 401, userMessage: '认证失败' },
  [ErrorCode.CSRF_TOKEN_INVALID]: { retryable: false, statusCode: 403, userMessage: 'CSRF 校验失败，请刷新页面后重试' },
  [ErrorCode.LLM_API_KEY_STALE]: { retryable: false, statusCode: 401, userMessage: '模型服务 API Key 已失效，请在设置页重新录入' },
  [ErrorCode.LLM_RATE_LIMITED]: { retryable: true, statusCode: 429, userMessage: '模型服务限流，请稍后重试' },
  [ErrorCode.LLM_PROVIDER_UNAVAILABLE]: { retryable: true, statusCode: 503, userMessage: '模型服务暂不可用，请稍后重试' },
  [ErrorCode.LLM_CONTEXT_LENGTH_EXCEEDED]: { retryable: false, statusCode: 400, userMessage: '对话上下文超长，请新建会话或精简消息' },
  [ErrorCode.LLM_CALL_FAILED]: { retryable: false, statusCode: 502, userMessage: '模型调用失败' },
  [ErrorCode.FAILOVER_TOTAL_TIMEOUT]: { retryable: true, statusCode: 504, userMessage: '故障转移链路总超时，请稍后重试' },
  [ErrorCode.FAILOVER_ALL_CANDIDATES_FAILED]: { retryable: true, statusCode: 503, userMessage: '所有候选模型均不可用，请稍后重试' },
  [ErrorCode.SYSTEM_ALREADY_INITIALIZED]: { retryable: false, statusCode: 409, userMessage: '系统已初始化' },
  [ErrorCode.WEAK_PASSWORD]: { retryable: false, statusCode: 400, userMessage: '密码强度不足' },
  [ErrorCode.PREREQUISITE_FAILED]: { retryable: false, statusCode: 412, userMessage: '前置条件未满足' },
  [ErrorCode.INIT_LOCK_CONTENTION]: { retryable: true, statusCode: 503, userMessage: '初始化锁竞争，请稍后重试' },
  [ErrorCode.RESOURCE_NOT_FOUND]: { retryable: false, statusCode: 404, userMessage: '资源不存在' },
  [ErrorCode.CONVERSATION_NOT_FOUND]: { retryable: false, statusCode: 404, userMessage: '会话不存在' },
  [ErrorCode.VALIDATION_ERROR]: { retryable: false, statusCode: 422, userMessage: '输入校验失败' },
  [ErrorCode.INVALID_INPUT]: { retryable: false, statusCode: 400, userMessage: '输入不合法' },
  [ErrorCode.RATE_LIMIT_EXCEEDED]: { retryable: true, statusCode: 429, userMessage: '请求过于频繁，请稍后重试' },
}

/**
 * 从 Error 对象中提取后端返回的 code 字段。
 * api.ts 的 createStreamError 会将后端 error.code 挂载到 Error.code 属性上。
 */
export function extractErrorCode(error: Error): string | undefined {
  const code = (error as { code?: unknown }).code
  return typeof code === 'string' ? code : undefined
}

/**
 * 从 Error 对象中提取后端返回的 retryable 字段。
 * api.ts 的 createStreamError 也会挂载 retryable 字段。
 */
export function extractRetryable(error: Error): boolean | undefined {
  const retryable = (error as { retryable?: unknown }).retryable
  return typeof retryable === 'boolean' ? retryable : undefined
}

/**
 * 根据错误码获取元信息。未注册的 code 返回 undefined。
 */
export function getErrorCodeMeta(code: string | undefined): ErrorCodeMeta | undefined {
  if (!code) {
    return undefined
  }
  return REGISTRY[code]
}

/**
 * 判断错误是否可重试。
 *
 * 优先级：
 * 1. Error 对象上显式挂载的 retryable 字段（后端 createStreamError 挂载）
 * 2. 错误码注册表中的 retryable 字段
 * 3. 兜底回退到字符串匹配 message 的旧逻辑（向后兼容）
 */
export function isRetryableError(error: Error): boolean {
  // 优先读后端显式返回的 retryable
  const explicitRetryable = extractRetryable(error)
  if (explicitRetryable !== undefined) {
    return explicitRetryable
  }
  // 其次按 code 查注册表
  const code = extractErrorCode(error)
  const meta = getErrorCodeMeta(code)
  if (meta) {
    return meta.retryable
  }
  // 兜底：字符串匹配 message（旧逻辑，向后兼容）
  const message = String(error.message || '').toLowerCase()
  return [
    'failed to fetch',
    'network',
    'stream',
    'timeout',
    'load failed',
    'econnreset',
  ].some((keyword) => message.includes(keyword))
}
