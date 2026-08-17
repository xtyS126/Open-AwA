import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// 使用 vi.hoisted 提前建立 mock 引用，避免循环依赖
const apiMocks = vi.hoisted(() => ({
  getPreferences: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  userAPI: {
    getPreferences: apiMocks.getPreferences,
  },
}))

import {
  loadServerPreferences,
  __resetPreferenceThrottle,
} from '@/shared/utils/preferenceSync'

describe('loadServerPreferences - 5 秒节流', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.clear()
    __resetPreferenceThrottle()
  })

  afterEach(() => {
    // 确保每个用例后恢复真实定时器，避免影响后续用例
    vi.useRealTimers()
  })

  it('5 秒内复用 Promise（仅发起一次请求）', async () => {
    apiMocks.getPreferences.mockResolvedValue({
      data: { preferences: { theme: 'dark' } },
    })

    const first = await loadServerPreferences()
    const second = await loadServerPreferences()

    expect(apiMocks.getPreferences).toHaveBeenCalledTimes(1)
    // 两次调用返回相同结果
    expect(first).toEqual({ theme: 'dark' })
    expect(second).toEqual({ theme: 'dark' })
  })

  it('失败不缓存：返回 null 后下次调用立即重试', async () => {
    apiMocks.getPreferences.mockRejectedValueOnce(new Error('网络不可达'))

    const firstResult = await loadServerPreferences()
    expect(firstResult).toBeNull()

    // 第二次调用前将 mock 改为成功响应
    apiMocks.getPreferences.mockResolvedValueOnce({
      data: { preferences: { theme: 'light' } },
    })

    const secondResult = await loadServerPreferences()
    expect(secondResult).toEqual({ theme: 'light' })

    // 失败后立即重试：总共调用 2 次（失败 1 次 + 成功 1 次）
    expect(apiMocks.getPreferences).toHaveBeenCalledTimes(2)
  })

  it('超过 5 秒后重新发起请求', async () => {
    vi.useFakeTimers()
    apiMocks.getPreferences.mockResolvedValue({
      data: { preferences: { theme: 'dark' } },
    })

    await loadServerPreferences()
    expect(apiMocks.getPreferences).toHaveBeenCalledTimes(1)

    // 推进时间超过节流窗口（5001ms > 5000ms）
    vi.advanceTimersByTime(5001)

    await loadServerPreferences()
    expect(apiMocks.getPreferences).toHaveBeenCalledTimes(2)
  })

  it('并发调用复用同一 Promise（仅发起一次请求）', async () => {
    // 用微任务延迟模拟异步响应，确保 Promise.all 内 3 个调用都在首个 promise 完成前发起
    apiMocks.getPreferences.mockImplementation(
      () => new Promise((resolve) => {
        Promise.resolve().then(() => {
          resolve({ data: { preferences: { theme: 'dark' } } })
        })
      })
    )

    const [r1, r2, r3] = await Promise.all([
      loadServerPreferences(),
      loadServerPreferences(),
      loadServerPreferences(),
    ])

    expect(apiMocks.getPreferences).toHaveBeenCalledTimes(1)
    expect(r1).toEqual({ theme: 'dark' })
    expect(r2).toEqual({ theme: 'dark' })
    expect(r3).toEqual({ theme: 'dark' })
  })
})
