/**
 * 日期格式化工具 — 基于 Intl.DateTimeFormat 和 i18n locale 的统一日期/时间显示。
 *
 * 使用示例：
 *   import { formatDate, formatTime, formatDateTime, formatRelative } from '@/shared/utils/dateFormat'
 *   formatDate(new Date(), 'zh-CN')           // "2026年6月6日"
 *   formatTime(new Date(), 'en-US')           // "2:30 PM"
 *   formatDateTime('2026-06-06T14:30:00')     // 自动使用当前 locale
 *   formatRelative(someDate)                   // "3 分钟前" / "3 minutes ago"
 */

import { useI18nStore } from '@/i18n'

/** 获取当前 locale 对应的 Intl locale 字符串 */
function getIntlLocale(locale?: string): string {
  const resolved = locale || (typeof window !== 'undefined' ? useI18nStore.getState().locale : undefined) || 'zh-CN'
  return resolved
}

/**
 * 格式化日期（不含时间）。
 * 示例：zh-CN → "2026年6月6日", en-US → "June 6, 2026"
 */
export function formatDate(
  date: Date | string | number,
  locale?: string
): string {
  const d = toDate(date)
  const loc = getIntlLocale(locale)
  return new Intl.DateTimeFormat(loc, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  }).format(d)
}

/**
 * 格式化时间（不含日期）。
 * 示例：zh-CN → "14:30", en-US → "2:30 PM"
 */
export function formatTime(
  date: Date | string | number,
  locale?: string
): string {
  const d = toDate(date)
  const loc = getIntlLocale(locale)
  return new Intl.DateTimeFormat(loc, {
    hour: '2-digit',
    minute: '2-digit',
  }).format(d)
}

/**
 * 格式化完整日期时间。
 * 示例：zh-CN → "2026年6月6日 14:30", en-US → "June 6, 2026, 2:30 PM"
 */
export function formatDateTime(
  date: Date | string | number,
  locale?: string
): string {
  const d = toDate(date)
  const loc = getIntlLocale(locale)
  return new Intl.DateTimeFormat(loc, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(d)
}

/**
 * 格式化简短日期（数字格式）。
 * 示例：zh-CN → "2026/6/6", en-US → "6/6/2026"
 */
export function formatShortDate(
  date: Date | string | number,
  locale?: string
): string {
  const d = toDate(date)
  const loc = getIntlLocale(locale)
  return new Intl.DateTimeFormat(loc, {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  }).format(d)
}

/**
 * 相对时间描述。
 * 示例："3 分钟前"、"2 小时前"、"昨天"、"3 天前"
 */
export function formatRelative(
  date: Date | string | number,
  locale?: string
): string {
  const d = toDate(date)
  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffSeconds = Math.floor(diffMs / 1000)
  const diffMinutes = Math.floor(diffSeconds / 60)
  const diffHours = Math.floor(diffMinutes / 60)
  const diffDays = Math.floor(diffHours / 24)

  const loc = getIntlLocale(locale)
  const isZh = loc.startsWith('zh')
  const isJa = loc.startsWith('ja')

  // 未来时间
  if (diffSeconds < 0) {
    return isZh ? '刚刚' : isJa ? 'たった今' : 'just now'
  }

  // 1 分钟内
  if (diffSeconds < 60) {
    return isZh ? '刚刚' : isJa ? 'たった今' : 'just now'
  }

  // 1 小时内
  if (diffMinutes < 60) {
    if (isZh || isJa) {
      return `${diffMinutes} 分钟前`
    }
    return diffMinutes === 1 ? '1 minute ago' : `${diffMinutes} minutes ago`
  }

  // 24 小时内
  if (diffHours < 24) {
    if (isZh || isJa) {
      return `${diffHours} 小时前`
    }
    return diffHours === 1 ? '1 hour ago' : `${diffHours} hours ago`
  }

  // 昨天
  if (diffDays === 1) {
    return isZh ? '昨天' : isJa ? '昨日' : 'yesterday'
  }

  // 7 天内
  if (diffDays < 7) {
    if (isZh || isJa) {
      return `${diffDays} 天前`
    }
    return `${diffDays} days ago`
  }

  // 超过 7 天，显示格式化日期
  return formatDate(d, loc)
}

/** 将多种日期输入统一转换为 Date 对象，无效输入抛出错误 */
function toDate(date: Date | string | number): Date {
  if (date instanceof Date) {
    if (Number.isNaN(date.getTime())) throw new RangeError('Invalid date')
    return date
  }
  const d = new Date(date)
  if (Number.isNaN(d.getTime())) throw new RangeError('Invalid date')
  return d
}
