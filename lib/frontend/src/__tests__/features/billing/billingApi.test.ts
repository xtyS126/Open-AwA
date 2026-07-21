import { describe, it, expect, vi, beforeEach } from 'vitest'
import { billingAPI, syncModelCatalog } from '@/features/billing/billingApi'

// mock api 模块，避免发起真实 HTTP 请求
const apiMocks = vi.hoisted(() => ({
  post: vi.fn(),
  get: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  default: apiMocks,
}))

describe('billingApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('loads module', () => {
    expect(billingAPI).toBeDefined()
    expect(syncModelCatalog).toBeDefined()
  })

  describe('syncModelCatalog', () => {
    it('calls POST /billing/sync-catalog and returns result data', async () => {
      // 模拟后端返回的同步统计结果
      const mockResult = {
        success: true,
        added: 5,
        updated: 3,
        removed: 1,
        skipped: 12,
        synced_at: '2026-07-10T08:00:00Z',
        dry_run: false,
      }
      apiMocks.post.mockResolvedValue({ data: mockResult })

      const result = await syncModelCatalog()

      // 验证调用了正确的端点
      expect(apiMocks.post).toHaveBeenCalledTimes(1)
      expect(apiMocks.post).toHaveBeenCalledWith('/billing/sync-catalog')
      // 验证返回值为 response.data（而非整个 response）
      expect(result).toEqual(mockResult)
      expect(result.added).toBe(5)
      expect(result.updated).toBe(3)
      expect(result.removed).toBe(1)
      expect(result.skipped).toBe(12)
      expect(result.synced_at).toBe('2026-07-10T08:00:00Z')
    })

    it('handles API error gracefully', async () => {
      // 模拟后端返回 502 错误（同步失败）
      const mockError = {
        response: {
          status: 502,
          data: { detail: '模型目录同步失败: 上游服务不可用' },
        },
      }
      apiMocks.post.mockRejectedValue(mockError)

      // syncModelCatalog 应抛出错误，由调用方捕获
      await expect(syncModelCatalog()).rejects.toEqual(mockError)
      expect(apiMocks.post).toHaveBeenCalledTimes(1)
    })

    it('handles network error gracefully', async () => {
      // 模拟网络异常（无 response 字段）
      const networkError = new Error('Network Error')
      apiMocks.post.mockRejectedValue(networkError)

      await expect(syncModelCatalog()).rejects.toThrow('Network Error')
    })
  })

  describe('billingAPI.syncModelCatalog', () => {
    it('exposes syncModelCatalog as a method returning axios response', async () => {
      // billingAPI.syncModelCatalog 返回 axios response（含 .data），
      // 与顶层 syncModelCatalog 函数（返回 .data）不同，便于调用方按需处理
      const mockResult = {
        success: true,
        added: 2,
        updated: 0,
        removed: 0,
        skipped: 8,
        synced_at: '2026-07-10T09:00:00Z',
      }
      apiMocks.post.mockResolvedValue({ data: mockResult })

      const response = await billingAPI.syncModelCatalog()

      expect(apiMocks.post).toHaveBeenCalledWith('/billing/sync-catalog')
      expect(response.data).toEqual(mockResult)
    })
  })
})
