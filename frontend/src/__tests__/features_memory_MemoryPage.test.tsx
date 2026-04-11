import '@testing-library/jest-dom/vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import MemoryPage from '@/features/memory/MemoryPage'
import { BrowserRouter } from 'react-router-dom'

const { getShortTermMock, getLongTermMock, getRecordsPreviewMock } = vi.hoisted(() => ({
  getShortTermMock: vi.fn(),
  getLongTermMock: vi.fn(),
  getRecordsPreviewMock: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  pluginsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  weixinAPI: { getConfig: vi.fn().mockResolvedValue({ data: {} }) },
  authAPI: { getMe: vi.fn().mockResolvedValue({ data: {} }) },
  billingAPI: { getSummary: vi.fn().mockResolvedValue({ data: {} }) },
  chatAPI: { getHistory: vi.fn().mockResolvedValue({ data: [] }) },
  modelsAPI: { getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }) },
  memoryAPI: { getShortTerm: getShortTermMock, getLongTerm: getLongTermMock, deleteShortTerm: vi.fn(), deleteLongTerm: vi.fn() },
  experiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  fileExperiencesAPI: { getList: vi.fn().mockResolvedValue({ data: [] }) },
  skillsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  promptsAPI: { getAll: vi.fn().mockResolvedValue({ data: [] }) },
  logsAPI: { query: vi.fn().mockResolvedValue({ data: { records: [], total: 0 } }) },
  behaviorAPI: { getStats: vi.fn().mockResolvedValue({ data: {} }) },
  conversationAPI: { getRecordsPreview: getRecordsPreviewMock }
}))

vi.mock('@/features/settings/modelsApi', () => ({
  modelsAPI: {
    getConfigurations: vi.fn().mockResolvedValue({ data: { configurations: [] } }),
    updateConfiguration: vi.fn().mockResolvedValue({ data: {} })
  }
}))

describe('MemoryPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getLongTermMock.mockResolvedValue({ data: [] })
  })

  it('短期记忆优先使用最近会话而不是默认 session_id', async () => {
    getRecordsPreviewMock.mockResolvedValue({
      data: {
        records: [{ session_id: 'session-123' }],
        count: 1,
        limit: 20,
      },
    })
    getShortTermMock.mockResolvedValue({ data: [] })

    render(<BrowserRouter><MemoryPage /></BrowserRouter>)

    await waitFor(() => expect(getShortTermMock).toHaveBeenCalledWith('session-123'))
    expect(getShortTermMock).not.toHaveBeenCalledWith('default')
    expect(await screen.findByText('当前查看会话：session-123')).toBeInTheDocument()
  })
})
