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
