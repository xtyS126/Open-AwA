/**
 * 安全的 localStorage 读写工具函数。
 * 在无痕浏览模式或存储权限受限时不会抛出异常。
 */

export function safeGetItem(key: string, defaultValue: string = ''): string {
  try {
    return localStorage.getItem(key) ?? defaultValue
  } catch {
    return defaultValue
  }
}

export function safeSetItem(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // 存储不可用时静默失败，不影响内存状态
  }
}

export function safeGetJsonItem<T>(key: string, defaultValue: T): T {
  const raw = safeGetItem(key, '')
  if (!raw) {
    return defaultValue
  }

  try {
    return JSON.parse(raw) as T
  } catch {
    return defaultValue
  }
}

export function safeSetJsonItem(key: string, value: unknown): boolean {
  try {
    localStorage.setItem(key, JSON.stringify(value))
    return true
  } catch {
    return false
  }
}
