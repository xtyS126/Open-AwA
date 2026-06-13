/**
 * 错误消息提取工具
 * 从 API 错误对象中提取用户友好的具体错误信息
 */
import { getApiErrorDetail } from '@/shared/api/client'

/**
 * 判断是否为网络错误
 */
function isNetworkError(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  const message = error.message.toLowerCase()
  return [
    'network',
    'failed to fetch',
    'net::err',
    'load failed',
    'econnreset',
    'econnrefused',
    'timeout',
    'aborted',
  ].some((keyword) => message.includes(keyword))
}

/**
 * 判断是否为权限错误
 */
function isPermissionError(error: unknown): boolean {
  const status = (error as { response?: { status?: number } })?.response?.status
  return status === 401 || status === 403
}

/**
 * 从错误对象中提取用户友好的错误消息
 *
 * 优先级：
 * 1. 网络错误 -> "网络连接失败，请检查网络后重试"
 * 2. 权限错误 -> "权限不足，请登录后重试"
 * 3. API 返回的具体错误信息（detail / message）
 * 4. 兜底消息
 */
export function getErrorMessage(error: unknown, fallback: string): string {
  // 网络错误
  if (isNetworkError(error)) {
    return '网络连接失败，请检查网络后重试'
  }

  // 权限错误
  if (isPermissionError(error)) {
    const status = (error as { response?: { status?: number } })?.response?.status
    if (status === 401) {
      return '登录已过期，请重新登录'
    }
    return '权限不足，无法执行此操作'
  }

  // API 返回的具体错误信息
  const apiDetail = getApiErrorDetail(error)
  if (apiDetail) {
    return apiDetail
  }

  // 兜底消息
  return fallback
}
