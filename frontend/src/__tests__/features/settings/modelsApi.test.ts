import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }))
// modelsApi 已改为直接从 client 导入 axios 实例，不再经由 api.ts barrel
vi.mock('@/shared/api/client', () => ({ api: apiMocks }))

import { modelsAPI } from '@/features/settings/modelsApi'

describe('modelsAPI', () => {
  beforeEach(() => vi.clearAllMocks())

  it('creates configurations with the supplied provider and model', async () => {
    apiMocks.post.mockResolvedValue({ data: { id: 1 } })
    await modelsAPI.createConfiguration({ provider: 'openai', model: 'gpt-4o-mini' })
    expect(apiMocks.post).toHaveBeenCalledWith('/billing/configurations', { provider: 'openai', model: 'gpt-4o-mini' })
  })

  it('updates parameter values on the scoped configuration endpoint', async () => {
    apiMocks.put.mockResolvedValue({ data: {} })
    await modelsAPI.updateParameters(8, { temperature: 0.2 })
    expect(apiMocks.put).toHaveBeenCalledWith('/billing/configurations/8/parameters', { temperature: 0.2 })
  })

  it('propagates configuration deletion failures', async () => {
    apiMocks.delete.mockRejectedValue(new Error('forbidden'))
    await expect(modelsAPI.deleteConfiguration(8)).rejects.toThrow('forbidden')
  })
})
