import { createElement, StrictMode, type ReactNode } from 'react'
import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  __resetConversationListCacheForTests,
  useConversationHistory,
} from '@/features/chat/hooks/useConversationHistory'

const apiMocks = vi.hoisted(() => ({
  listSessions: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  conversationAPI: {
    listSessions: apiMocks.listSessions,
  },
}))

function strictModeWrapper({ children }: { children: ReactNode }) {
  return createElement(StrictMode, null, children)
}

describe('useConversationHistory', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    __resetConversationListCacheForTests()
    apiMocks.listSessions.mockResolvedValue({
      data: {
        items: [],
        total: 0,
        page: 1,
        page_size: 20,
        has_more: false,
      },
    })
  })

  it('StrictMode effect 重放时复用相同参数的在途列表请求', async () => {
    const { unmount } = renderHook(() => useConversationHistory(), {
      wrapper: strictModeWrapper,
    })

    await waitFor(() => {
      expect(apiMocks.listSessions).toHaveBeenCalledTimes(1)
    })

    unmount()
  })
})
