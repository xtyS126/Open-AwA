import { describe, it, expect, beforeEach, vi } from 'vitest'

// 在导入 client 之前 mock window 对象
describe('API_BASE_URL 动态解析', () => {
  beforeEach(() => {
    // 每个测试前重置 window 状态
    vi.resetModules()
    localStorage.clear()
    // 重置 window 注入对象
    delete (window as unknown as { __OPENAWA_BACKEND__?: unknown }).__OPENAWA_BACKEND__
  })

  it('优先级 1：使用 preload 注入的 __OPENAWA_BACKEND__.url', async () => {
    ;(window as unknown as { __OPENAWA_BACKEND__?: { url: string } }).__OPENAWA_BACKEND__ = {
      url: 'http://remote-backend:8000/api',
    }
    const { API_BASE_URL } = await import('@/shared/api/client')
    expect(API_BASE_URL).toBe('http://remote-backend:8000/api')
  })

  it('优先级 2：使用 localStorage 中的 openawa_backend_url', async () => {
    localStorage.setItem('openawa_backend_url', 'http://stored-backend:9000/api')
    const { API_BASE_URL } = await import('@/shared/api/client')
    expect(API_BASE_URL).toBe('http://stored-backend:9000/api')
  })

  it('优先级 3：默认返回 /api（web 模式）', async () => {
    const { API_BASE_URL } = await import('@/shared/api/client')
    expect(API_BASE_URL).toBe('/api')
  })

  it('preload 注入优先级高于 localStorage', async () => {
    ;(window as unknown as { __OPENAWA_BACKEND__?: { url: string } }).__OPENAWA_BACKEND__ = {
      url: 'http://preload-backend:8000/api',
    }
    localStorage.setItem('openawa_backend_url', 'http://stored-backend:9000/api')
    const { API_BASE_URL } = await import('@/shared/api/client')
    expect(API_BASE_URL).toBe('http://preload-backend:8000/api')
  })
})

describe('setBackendUrl', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
  })

  it('将 URL 写入 localStorage', async () => {
    const { setBackendUrl } = await import('@/shared/api/client')
    setBackendUrl('http://new-backend:8000/api')
    expect(localStorage.getItem('openawa_backend_url')).toBe('http://new-backend:8000/api')
  })
})

describe('isBackendConfigured', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
    // 清除前序 describe 注入的 preload 配置，避免跨用例污染
    delete (window as unknown as { __OPENAWA_BACKEND__?: unknown }).__OPENAWA_BACKEND__
  })

  it('Web 模式：局域网后端 URL 视为已配置', async () => {
    localStorage.setItem('openawa_backend_url', 'http://192.168.2.3:8000/api')
    const { isBackendConfigured } = await import('@/shared/api/client')
    expect(isBackendConfigured()).toBe(true)
  })

  it('无 URL 时视为未配置', async () => {
    const { isBackendConfigured } = await import('@/shared/api/client')
    expect(isBackendConfigured()).toBe(false)
  })

  it('原生容器内 localhost/127.0.0.1 残留视为未配置', async () => {
    // 模拟原生容器：platform.isNativeApp 返回 true
    vi.doMock('@/shared/utils/platform', () => ({ isNativeApp: () => true }))
    localStorage.setItem('openawa_backend_url', 'http://127.0.0.1:8000/api')
    const { isBackendConfigured } = await import('@/shared/api/client')
    expect(isBackendConfigured()).toBe(false)
    vi.doUnmock('@/shared/utils/platform')
  })

  it('原生容器内局域网 URL 视为已配置', async () => {
    vi.doMock('@/shared/utils/platform', () => ({ isNativeApp: () => true }))
    localStorage.setItem('openawa_backend_url', 'http://192.168.2.3:8000/api')
    const { isBackendConfigured } = await import('@/shared/api/client')
    expect(isBackendConfigured()).toBe(true)
    vi.doUnmock('@/shared/utils/platform')
  })
})

describe('refreshCsrfToken', () => {
  beforeEach(() => {
    vi.resetModules()
    localStorage.clear()
    sessionStorage.clear()
  })

  it('未认证时不请求受保护的 CSRF 端点', async () => {
    const { api, clearCachedApiKey, refreshCsrfToken } = await import('@/shared/api/client')
    const getSpy = vi.spyOn(api, 'get')
    clearCachedApiKey()

    await refreshCsrfToken()

    expect(getSpy).not.toHaveBeenCalled()
  })
})

describe('请求取消分类', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('将 Axios 取消与浏览器 AbortError 识别为预期控制流', async () => {
    const { isExpectedRequestCancellation } = await import('@/shared/api/client')

    expect(isExpectedRequestCancellation({ code: 'ERR_CANCELED' })).toBe(true)
    expect(isExpectedRequestCancellation(new DOMException('请求已取消', 'AbortError'))).toBe(true)
    expect(isExpectedRequestCancellation(new Error('网络失败'))).toBe(false)
  })
})
