import { describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }))
vi.mock('@/shared/api/api', () => ({ default: apiMocks }))

import { billingAPI } from '@/features/billing/billing'

describe('billing compatibility entry', () => {
  it('forwards catalog synchronization through the canonical API implementation', async () => {
    apiMocks.post.mockResolvedValue({ data: { added: 1 } })
    await expect(billingAPI.syncModelCatalog()).resolves.toEqual({ data: { added: 1 } })
    expect(apiMocks.post).toHaveBeenCalledWith('/billing/sync-catalog')
  })

  it('surfaces failed catalog synchronization requests to callers', async () => {
    apiMocks.post.mockRejectedValue(new Error('offline'))
    await expect(billingAPI.syncModelCatalog()).rejects.toThrow('offline')
  })
})
