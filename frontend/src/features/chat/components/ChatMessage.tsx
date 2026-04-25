import { memo } from 'react'
import type { ChatMessage as ChatMessageType } from '@/features/chat/types'
import type { AssistantExecutionMeta } from '@/features/chat/types'
import { ReasoningContent } from './ReasoningContent'
import { MessageContent } from './MessageContent'
import AssistantExecutionDetails from './AssistantExecutionDetails'
import { hasExecutionMeta } from '@/features/chat/utils/executionMeta'
import styles from '../ChatPage.module.css'

interface ChatMessageProps {
  message: ChatMessageType
  messageMeta: Record<string, AssistantExecutionMeta>
  streamingAssistantId: string | null
  isLastMessage: boolean
}

function ChatMessageInner({ message, messageMeta, streamingAssistantId, isLastMessage }: ChatMessageProps) {
  const isCurrentlyStreaming = streamingAssistantId === message.id && isLastMessage && message.role === 'assistant'

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
