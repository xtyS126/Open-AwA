import { useCallback, useMemo, useState } from 'react'

export type StreamConnectionState = 'idle' | 'connecting' | 'streaming' | 'retrying' | 'error'

export function getStreamStatusText(
  state: StreamConnectionState,
  retryCount: number,
  errorMessage: string | null,
  stageMessage: string | null
): string {
  switch (state) {
    case 'error':
      return errorMessage ? `流式连接失败：${errorMessage}` : '流式连接失败'
    case 'retrying':
      return `正在重连流式通道（第 ${retryCount} 次）`
    case 'connecting':
      return '正在连接流式通道'
    case 'streaming':
      return stageMessage || '正在流式生成'
    default:
      return ''
  }
}

/**
 * 统一管理聊天页流式请求的连接状态、阶段文案与错误信息。
 */
export function useStreamExecutionState() {
  const [streamConnectionState, setStreamConnectionState] = useState<StreamConnectionState>('idle')
  const [streamRetryCount, setStreamRetryCount] = useState(0)
  const [streamErrorMessage, setStreamErrorMessage] = useState<string | null>(null)
  const [streamStageMessage, setStreamStageMessage] = useState<string | null>(null)

  const resetStreamExecutionState = useCallback(() => {
    setStreamConnectionState('idle')
    setStreamRetryCount(0)
    setStreamErrorMessage(null)
    setStreamStageMessage(null)
  }, [])

  const beginStreamExecution = useCallback((outputMode: 'stream' | 'direct') => {
    setStreamErrorMessage(null)
    setStreamRetryCount(0)
    setStreamStageMessage(null)
    setStreamConnectionState(outputMode === 'stream' ? 'connecting' : 'idle')
  }, [])

  const markStreamRetrying = useCallback((attempt: number) => {
    setStreamRetryCount(attempt)
    setStreamConnectionState('retrying')
  }, [])

  const markStreamStreaming = useCallback(() => {
    setStreamConnectionState('streaming')
    setStreamErrorMessage(null)
  }, [])

  const markStreamFailed = useCallback((message: string) => {
    setStreamConnectionState('error')
    setStreamErrorMessage(message)
  }, [])

  const clearStreamStageMessage = useCallback(() => {
    setStreamStageMessage(null)
  }, [])

  const setIdleStreamState = useCallback(() => {
    setStreamConnectionState('idle')
  }, [])

  const streamStatusText = useMemo(
    () => getStreamStatusText(streamConnectionState, streamRetryCount, streamErrorMessage, streamStageMessage),
    [streamConnectionState, streamRetryCount, streamErrorMessage, streamStageMessage]
  )

  return {
    streamConnectionState,
    streamRetryCount,
    streamErrorMessage,
    streamStageMessage,
    streamStatusText,
    setStreamStageMessage,
    beginStreamExecution,
    markStreamRetrying,
    markStreamStreaming,
    markStreamFailed,
    clearStreamStageMessage,
    setIdleStreamState,
    resetStreamExecutionState,
  }
}