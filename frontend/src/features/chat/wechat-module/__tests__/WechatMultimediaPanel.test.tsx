import { act, render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WechatMultimediaPanel from '../WechatMultimediaPanel'
import { listMultimedia, listMultimediaAssets } from '@/shared/api/weixinMultimediaApi'
import { useWeixinWebSocket } from '@/shared/hooks/useWeixinWebSocket'
import type { WeixinWsEvent } from '@/shared/api/api'

vi.mock('@/shared/api/weixinMultimediaApi', () => ({
  listMultimedia: vi.fn().mockResolvedValue([]),
  listMultimediaAssets: vi.fn().mockResolvedValue([]),
  sendMultimedia: vi.fn(),
  transcribeMultimediaAsset: vi.fn(),
}))

vi.mock('@/shared/hooks/useWeixinWebSocket', () => ({
  useWeixinWebSocket: vi.fn().mockReturnValue({ connected: false, error: null, close: vi.fn(), reconnect: vi.fn() }),
}))

describe('WechatMultimediaPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listMultimedia).mockResolvedValue([])
    vi.mocked(listMultimediaAssets).mockResolvedValue([])
    vi.mocked(useWeixinWebSocket).mockReturnValue({ connected: false, error: null, close: vi.fn(), reconnect: vi.fn() })
  })

  it('receives realtime messages and refreshes the multimedia list', async () => {
    await act(async () => {
      render(<WechatMultimediaPanel />)
    })
    await waitFor(() => expect(listMultimedia).toHaveBeenCalledTimes(1))

    const websocketOptions = vi.mocked(useWeixinWebSocket).mock.calls.at(-1)?.[0]
    const event: Extract<WeixinWsEvent, { event: 'new_message' }> = {
      event: 'new_message',
      message_id: 'message-1',
      from_user_id: 'user-1',
      text: '',
      message_type: 'voice',
      multimedia: null,
      timestamp: '2026-07-13T00:00:00+00:00',
    }

    await act(async () => {
      websocketOptions?.onMessage?.(event)
    })
    await waitFor(() => expect(listMultimedia).toHaveBeenCalledTimes(2))
  })
})
