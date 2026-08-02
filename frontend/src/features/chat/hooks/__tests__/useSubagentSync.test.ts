import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { MutableRefObject } from 'react'
import { useSubagentSync, type SendOptions, type UseSubagentSyncParams } from '../useSubagentSync'
import { createEmptyExecutionMeta } from '@/features/chat/utils/executionMeta'
import type { AssistantExecutionMeta } from '@/features/chat/types'

vi.mock('@/shared/api/taskRuntimeApi', () => ({
  getAgent: vi.fn(),
  getTranscript: vi.fn(),
}))

function createParams(
  messageMetaRef: MutableRefObject<Record<string, AssistantExecutionMeta>>,
  handleSendRef: MutableRefObject<((message?: string, attachments?: unknown[], options?: SendOptions) => Promise<void>) | undefined>
): UseSubagentSyncParams {
  return {
    updateAssistantMeta: vi.fn(),
    updateAssistantSegments: vi.fn(),
    addToast: vi.fn(),
    isMountedRef: { current: true },
    messageMetaRef,
    handleSendRef,
  }
}

describe('useSubagentSync 外部引用同步', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('重新渲染后使用最新的消息元数据和发送函数引用', async () => {
    const firstSend = vi.fn().mockResolvedValue(undefined)
    const secondSend = vi.fn().mockResolvedValue(undefined)
    const firstParams = createParams(
      { current: {} },
      { current: firstSend }
    )
    const completedMeta: AssistantExecutionMeta = {
      ...createEmptyExecutionMeta(),
      toolEvents: [{
        id: 'sub_local',
        kind: 'subagent',
        name: '研究代理',
        status: 'completed',
        detail: '聚合结果',
      }],
    }
    const secondParams = createParams(
      { current: { 'assistant-1': completedMeta } },
      { current: secondSend }
    )

    const { result, rerender } = renderHook(
      ({ params }) => useSubagentSync(params),
      { initialProps: { params: firstParams } }
    )

    rerender({ params: secondParams })

    act(() => {
      result.current.scheduleSubagentAggregation('assistant-1')
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(80)
    })

    expect(firstSend).not.toHaveBeenCalled()
    expect(secondSend).toHaveBeenCalledWith(
      expect.any(String),
      undefined,
      expect.objectContaining({ assistantMessageId: 'assistant-1' })
    )
  })
})
