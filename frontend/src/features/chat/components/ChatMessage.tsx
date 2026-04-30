import { memo, useMemo } from 'react'
import type { ChatMessage as ChatMessageType, ToolEventMeta } from '@/features/chat/types'
import type { AssistantExecutionMeta } from '@/features/chat/types'
import { ReasoningContent } from './ReasoningContent'
import { MessageContent } from './MessageContent'
import InlineToolCallCard from './InlineToolCallCard'
import AssistantExecutionDetails from './AssistantExecutionDetails'
import { hasExecutionMeta } from '@/features/chat/utils/executionMeta'
import styles from '../ChatPage.module.css'

interface ChatMessageProps {
  message: ChatMessageType
  messageMeta: Record<string, AssistantExecutionMeta>
  streamingAssistantId: string | null
  isLastMessage: boolean
}

function getSortedToolEvents(message: ChatMessageType, meta: AssistantExecutionMeta | undefined): ToolEventMeta[] {
  // 优先使用 messageMeta 中的实时数据
  const source = meta?.toolEvents || message.toolEvents || []
  return [...source].sort((a, b) => {
    if (a.sequence !== undefined && b.sequence !== undefined) {
      return a.sequence - b.sequence
    }
    if (a.sequence !== undefined) return -1
    if (b.sequence !== undefined) return 1
    return 0
  })
}

function ChatMessageInner({ message, messageMeta, streamingAssistantId, isLastMessage }: ChatMessageProps) {
  const isCurrentlyStreaming = streamingAssistantId === message.id && isLastMessage && message.role === 'assistant'

  const toolEvents = useMemo(() => {
    if (message.role !== 'assistant') return []
    return getSortedToolEvents(message, messageMeta[message.id])
  }, [message, messageMeta])

  const hasTools = toolEvents.length > 0

  return (
    <div className={`${styles['message']} ${message.role === 'user' ? styles['user'] : styles['assistant']}`}>
      <div className={styles['message-content']}>
        {message.reasoning_content && (
          <ReasoningContent
            messageId={message.id}
            content={message.reasoning_content}
            isStreaming={isCurrentlyStreaming}
          />
        )}
        {/* 内联工具调用卡片 */}
        {hasTools && (
          <div className={styles['inline-tools']}>
            {toolEvents.map((tool, index) => (
              <InlineToolCallCard
                key={tool.id}
                tool={tool}
                isLast={index === toolEvents.length - 1}
              />
            ))}
          </div>
        )}
        {message.content && <MessageContent content={message.content} role={message.role} />}
        {message.role === 'assistant' && messageMeta[message.id] && hasExecutionMeta(messageMeta[message.id]) && (
          <AssistantExecutionDetails
            messageId={message.id}
            meta={messageMeta[message.id]}
            isStreaming={isCurrentlyStreaming}
          />
        )}
      </div>
    </div>
  )
}

export const ChatMessage = memo(ChatMessageInner)
