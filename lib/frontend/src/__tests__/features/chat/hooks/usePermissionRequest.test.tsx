import { renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { usePermissionRequest } from '@/features/chat/hooks/usePermissionRequest'
import { useAuthStore } from '@/shared/store/authStore'

vi.mock('@/shared/api/securityApi', () => ({
  securityAPI: {
    requestSseTicket: vi.fn(),
    replyToPermission: vi.fn(),
  },
}))

describe('usePermissionRequest', () => {
  const eventSourceMock = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    eventSourceMock.mockImplementation(() => ({
      close: vi.fn(),
      addEventListener: vi.fn(),
    }))
    vi.stubGlobal('EventSource', eventSourceMock)
    useAuthStore.setState({
      user: null,
      apiKey: null,
      isAuthenticated: false,
      isInitialized: true,
    })
  })

  it('认证尚未确认时不连接受保护的权限 SSE', () => {
    renderHook(() => usePermissionRequest('conversation-1'))

    expect(eventSourceMock).not.toHaveBeenCalled()
  })
})
