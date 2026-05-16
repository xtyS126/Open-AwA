import type { AssistantMessageSegment } from '@/features/chat/types'
import { appendAssistantChunk } from '@/features/chat/utils/assistantSegments'

export interface StreamMessageBufferState {
  content: string
  reasoning: string
  lastUpdateTime: number
}

interface HandleStreamChunkEventOptions {
  assistantMessageId: string
  event: Record<string, unknown>
  assistantMessageCreated: boolean
  ensureAssistantMessage: (content?: string, reasoning?: string) => boolean
  updateAssistantSegments: (
    messageId: string,
    updater: (current: AssistantMessageSegment[] | undefined) => AssistantMessageSegment[],
  ) => void
  appendAssistantMessageText: (assistantMessageId: string, content: string, reasoningContent?: string) => void
  flushBuffer: (assistantMessageId?: string) => void
  buffer: StreamMessageBufferState
  isDocumentHidden: boolean
  getNow?: () => number
}

/**
 * 处理流式 chunk 事件，统一首条消息创建、隐藏标签页缓冲和前台直接刷新的分支。
 */
export function handleStreamChunkEvent(options: HandleStreamChunkEventOptions): boolean {
  const {
    assistantMessageId,
    event,
    assistantMessageCreated,
    ensureAssistantMessage,
    updateAssistantSegments,
    appendAssistantMessageText,
    flushBuffer,
    buffer,
    isDocumentHidden,
    getNow = Date.now,
  } = options

  const content = typeof event.content === 'string' ? event.content : ''
  const reasoning = typeof event.reasoning_content === 'string' ? event.reasoning_content : ''

  if (!assistantMessageCreated) {
    const didCreateAssistantMessage = ensureAssistantMessage(content, reasoning)
    buffer.lastUpdateTime = getNow()
    return didCreateAssistantMessage
  }

  if (content || reasoning) {
    updateAssistantSegments(assistantMessageId, (segments) => appendAssistantChunk(segments, {
      content,
      reasoningContent: reasoning,
    }))
  }

  if (isDocumentHidden) {
    buffer.content += content
    buffer.reasoning += reasoning
    const now = getNow()
    if (now - buffer.lastUpdateTime > 1000) {
      flushBuffer(assistantMessageId)
    }
    return true
  }

  if (buffer.content || buffer.reasoning) {
    appendAssistantMessageText(
      assistantMessageId,
      buffer.content + content,
      buffer.reasoning + reasoning,
    )
    buffer.content = ''
    buffer.reasoning = ''
    buffer.lastUpdateTime = getNow()
    return true
  }

  appendAssistantMessageText(assistantMessageId, content, reasoning)
  return true
}