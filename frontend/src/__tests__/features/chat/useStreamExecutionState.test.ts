import '@testing-library/jest-dom/vitest'
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { getStreamStatusText, useStreamExecutionState } from '@/features/chat/hooks/useStreamExecutionState'

describe('useStreamExecutionState', () => {
  it('starts from an idle and empty stream status', () => {
    const { result } = renderHook(() => useStreamExecutionState())

    expect(result.current.streamConnectionState).toBe('idle')
    expect(result.current.streamRetryCount).toBe(0)
    expect(result.current.streamErrorMessage).toBeNull()
    expect(result.current.streamStageMessage).toBeNull()
    expect(result.current.streamStatusText).toBe('')
  })

  it('tracks connecting, streaming, retrying and failure transitions', () => {
    const { result } = renderHook(() => useStreamExecutionState())

    act(() => {
      result.current.beginStreamExecution('stream')
    })
    expect(result.current.streamConnectionState).toBe('connecting')
    expect(result.current.streamStatusText).toBe('正在连接流式通道')

    act(() => {
      result.current.setStreamStageMessage('正在生成执行计划')
      result.current.markStreamStreaming()
    })
    expect(result.current.streamConnectionState).toBe('streaming')
    expect(result.current.streamStatusText).toBe('正在生成执行计划')

    act(() => {
      result.current.markStreamRetrying(1)
    })
    expect(result.current.streamRetryCount).toBe(1)
    expect(result.current.streamConnectionState).toBe('retrying')
    expect(result.current.streamStatusText).toBe('正在重连流式通道（第 1 次）')

    act(() => {
      result.current.markStreamFailed('网络中断')
    })
    expect(result.current.streamConnectionState).toBe('error')
    expect(result.current.streamErrorMessage).toBe('网络中断')
    expect(result.current.streamStatusText).toBe('流式连接失败：网络中断')
  })

  it('clears retry count, stage and error when resetting', () => {
    const { result } = renderHook(() => useStreamExecutionState())

    act(() => {
      result.current.beginStreamExecution('stream')
      result.current.setStreamStageMessage('处理中')
      result.current.markStreamRetrying(2)
      result.current.markStreamFailed('超时')
    })

    act(() => {
      result.current.resetStreamExecutionState()
    })

    expect(result.current.streamConnectionState).toBe('idle')
    expect(result.current.streamRetryCount).toBe(0)
    expect(result.current.streamErrorMessage).toBeNull()
    expect(result.current.streamStageMessage).toBeNull()
    expect(result.current.streamStatusText).toBe('')
  })
})

describe('getStreamStatusText', () => {
  it('falls back to default streaming text when no stage is present', () => {
    expect(getStreamStatusText('streaming', 0, null, null)).toBe('正在流式生成')
  })
})