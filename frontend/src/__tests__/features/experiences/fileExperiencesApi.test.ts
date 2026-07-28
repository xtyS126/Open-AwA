import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }))
vi.mock('@/shared/api/api', () => ({ default: apiMocks }))

import { fileExperiencesApi } from '@/features/experiences/fileExperiencesApi'

describe('fileExperiencesApi', () => {
  beforeEach(() => vi.clearAllMocks())

  it('encodes file names before loading details', async () => {
    apiMocks.get.mockResolvedValue({ data: {} })
    await fileExperiencesApi.getFileDetail('周报 / draft.md')
    expect(apiMocks.get).toHaveBeenCalledWith('/experience-files/%E5%91%A8%E6%8A%A5%20%2F%20draft.md')
  })

  it('saves content under the encoded file path', async () => {
    apiMocks.put.mockResolvedValue({ data: {} })
    await fileExperiencesApi.saveFile('notes.md', '内容')
    expect(apiMocks.put).toHaveBeenCalledWith('/experience-files/notes.md', { content: '内容' })
  })

  it('propagates file API failures', async () => {
    apiMocks.get.mockRejectedValue(new Error('unavailable'))
    await expect(fileExperiencesApi.listFiles()).rejects.toThrow('unavailable')
  })
})
