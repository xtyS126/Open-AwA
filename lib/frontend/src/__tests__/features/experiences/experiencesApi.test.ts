import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() }))
vi.mock('@/shared/api/api', () => ({ default: apiMocks }))

import { experiencesAPI } from '@/features/experiences/experiencesApi'

describe('experiencesAPI', () => {
  beforeEach(() => vi.clearAllMocks())

  it('passes search filters to the experiences endpoint', async () => {
    apiMocks.get.mockResolvedValue({ data: [] })
    await experiencesAPI.getExperiences({ experience_type: 'strategy', limit: 10 })
    expect(apiMocks.get).toHaveBeenCalledWith('/experiences', { params: { experience_type: 'strategy', limit: 10 } })
  })

  it('sends review approval through the expected endpoint', async () => {
    apiMocks.put.mockResolvedValue({ data: { reviewed: true } })
    await experiencesAPI.reviewExperience(7, true)
    expect(apiMocks.put).toHaveBeenCalledWith('/experiences/7/review', null, { params: { approved: true } })
  })

  it('propagates API failures to the caller', async () => {
    apiMocks.delete.mockRejectedValue(new Error('offline'))
    await expect(experiencesAPI.deleteExperience(7)).rejects.toThrow('offline')
  })
})
