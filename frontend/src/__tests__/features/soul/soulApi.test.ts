import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getProbes,
  getProfile,
  initProfile,
  respondProbe,
  updateOverrides,
} from '@/features/soul/soulApi'

const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  sharedApi: apiMocks,
}))

describe('soulApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('使用不重复 API 前缀的路径并解包画像响应', async () => {
    const profile = {
      user_id: '1',
      surface: { description: '', structured_data: {}, confidence: 0 },
      interest: { description: '', structured_data: {}, confidence: 0 },
      role: { description: '', structured_data: {}, confidence: 0 },
      values: { description: '', structured_data: {}, confidence: 0 },
      core: { description: '', structured_data: {}, confidence: 0 },
      updated_at: '2026-08-03T00:00:00Z',
    }
    apiMocks.get.mockResolvedValue({
      data: { success: true, data: profile, message: '获取画像成功' },
    })

    await expect(getProfile()).resolves.toEqual({ profile })
    expect(apiMocks.get).toHaveBeenCalledWith('/soul/profile')
  })

  it('解包探针并从推测依据中读取置信度', async () => {
    apiMocks.get.mockResolvedValue({
      data: {
        success: true,
        data: [{
          id: 7,
          hypothesis: '偏好类型安全',
          status: 'pending',
          probe_question: '是否偏好类型安全？',
          reasoning: { confidence: 0.72 },
        }],
        message: '获取到 1 个待确认探针',
      },
    })

    await expect(getProbes()).resolves.toEqual({
      probes: [{
        id: 7,
        hypothesis: '偏好类型安全',
        status: 'pending',
        probe_question: '是否偏好类型安全？',
        confidence: 0.72,
      }],
    })
    expect(apiMocks.get).toHaveBeenCalledWith('/soul/probes')
  })

  it('按后端契约发送画像覆盖层、探针响应和初始化请求', async () => {
    apiMocks.post.mockResolvedValue({ data: { success: true, data: null, message: '' } })
    const override = {
      layer_name: 'surface',
      field: 'description' as const,
      value: '新的描述',
    }

    await updateOverrides(override)
    await respondProbe(7, 'confirmed')
    await initProfile()

    expect(apiMocks.post).toHaveBeenNthCalledWith(1, '/soul/overrides', override)
    expect(apiMocks.post).toHaveBeenNthCalledWith(2, '/soul/probe/respond', {
      probe_id: 7,
      response: 'confirmed',
    })
    expect(apiMocks.post).toHaveBeenNthCalledWith(3, '/soul/init')
  })
})
