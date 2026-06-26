import type { AssistantExecutionMeta, ChatMessage } from '@/features/chat/types'
import { buildExecutionMetaFromPayload, hasExecutionMeta } from '@/features/chat/utils/executionMeta'
import { buildSegmentsFromLegacyMessage } from '@/features/chat/utils/assistantSegments'

interface ApplyDirectAssistantResponseOptions {
  assistantMessageId: string
  responseData: Record<string, unknown>
  addMessage: (
    role: 'assistant',
    content: string,
    reasoningContent: string | undefined,
    messageId: string,
  ) => void
  updateMessage: (messageId: string, updater: (message: ChatMessage) => ChatMessage) => void
  setMessageMeta: (
    updater: (current: Record<string, AssistantExecutionMeta>) => Record<string, AssistantExecutionMeta>,
  ) => void
  sanitizeDisplayedError: (message: string) => string
  dispatchUsageUpdated: (payload: { callId?: string; provider?: string; model?: string }) => void
}

function syncExecutionMeta(
  assistantMessageId: string,
  nextMeta: AssistantExecutionMeta,
  updateMessage: (messageId: string, updater: (message: ChatMessage) => ChatMessage) => void,
  setMessageMeta: (
    updater: (current: Record<string, AssistantExecutionMeta>) => Record<string, AssistantExecutionMeta>,
  ) => void,
  dispatchUsageUpdated: (payload: { callId?: string; provider?: string; model?: string }) => void,
) {
  if (hasExecutionMeta(nextMeta)) {
    setMessageMeta((prev) => ({ ...prev, [assistantMessageId]: nextMeta }))
    if (nextMeta.toolEvents.length > 0) {
      updateMessage(assistantMessageId, (message) => ({
        ...message,
        toolEvents: nextMeta.toolEvents,
      }))
    }
  }

  if (nextMeta.usage) {
    dispatchUsageUpdated({
      callId: nextMeta.usage.call_id,
      provider: nextMeta.usage.provider,
      model: nextMeta.usage.model,
    })
  }
}

/**
 * 统一处理 direct 模式返回，将文本、推理内容和执行元数据同步到消息与 store。
 */
export function applyDirectAssistantResponse(options: ApplyDirectAssistantResponseOptions): boolean {
  const {
    assistantMessageId,
    responseData,
    addMessage,
    updateMessage,
    setMessageMeta,
    sanitizeDisplayedError,
    dispatchUsageUpdated,
  } = options

  const assistantText = typeof responseData.response === 'string' ? responseData.response : ''
  const backendError = responseData.error
  const reasoningContent = typeof responseData.reasoning_content === 'string'
    ? responseData.reasoning_content
    : undefined
  const nextMeta = buildExecutionMetaFromPayload(responseData)

  if (assistantText.trim()) {
    addMessage('assistant', assistantText, reasoningContent, assistantMessageId)
    updateMessage(assistantMessageId, (message) => ({
      ...message,
      segments: buildSegmentsFromLegacyMessage({
        content: assistantText,
        reasoningContent,
        meta: nextMeta,
      }),
    }))
    syncExecutionMeta(assistantMessageId, nextMeta, updateMessage, setMessageMeta, dispatchUsageUpdated)
    return true
  }

  if (backendError && typeof backendError === 'object') {
    const errObj = backendError as Record<string, unknown>
    if (typeof errObj.message === 'string') {
      const backendErrorMessage = sanitizeDisplayedError(errObj.message)
      addMessage('assistant', `请求失败：${backendErrorMessage}`, undefined, assistantMessageId)
      updateMessage(assistantMessageId, (message) => ({
        ...message,
        segments: buildSegmentsFromLegacyMessage({
          content: `请求失败：${backendErrorMessage}`,
        }),
      }))
      return true
    }
  }

  if (reasoningContent || hasExecutionMeta(nextMeta)) {
    addMessage('assistant', '', reasoningContent, assistantMessageId)
    updateMessage(assistantMessageId, (message) => ({
      ...message,
      segments: buildSegmentsFromLegacyMessage({
        reasoningContent,
        meta: nextMeta,
      }),
    }))
    syncExecutionMeta(assistantMessageId, nextMeta, updateMessage, setMessageMeta, dispatchUsageUpdated)
    return true
  }

  addMessage('assistant', '抱歉，当前未返回有效内容，请稍后重试。', undefined, assistantMessageId)
  updateMessage(assistantMessageId, (message) => ({
    ...message,
    segments: buildSegmentsFromLegacyMessage({
      content: '抱歉，当前未返回有效内容，请稍后重试。',
      reasoningContent,
      meta: nextMeta,
    }),
  }))
  syncExecutionMeta(assistantMessageId, nextMeta, updateMessage, setMessageMeta, dispatchUsageUpdated)
  return true
}