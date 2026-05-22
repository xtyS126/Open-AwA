import type { ChatMessage as ChatMessageType, AssistantExecutionMeta } from '@/features/chat/types'
import { ChatMessage } from './ChatMessage'
import styles from '../ChatPage.module.css'

interface MessageListProps {
  messages: ChatMessageType[]
  messageMeta: Record<string, AssistantExecutionMeta>
  streamingAssistantId: string | null
  isLoading: boolean
  outputMode: 'stream' | 'direct'
  streamStatusText: string
  messagesEndRef: React.RefObject<HTMLDivElement | null>
  onEditMessage?: (content: string) => void
  onRegenerate?: (messageId: string) => void
  onFeedback?: (messageId: string, rating: 1 | -1) => void
  feedbackState?: Record<string, 1 | -1 | undefined>
  onUndo?: (operationId: string) => Promise<void>
}

export function MessageList({
  messages,
  messageMeta,
  streamingAssistantId,
  isLoading,
  outputMode,
  streamStatusText,
  messagesEndRef,
  onEditMessage,
  onRegenerate,
  onFeedback,
  feedbackState,
  onUndo,
}: MessageListProps) {
  return (
    <div className={styles['chat-messages']}>
      {messages.length === 0 && (
        <div className={styles['chat-empty']}>
          <p>Hello! How can I help you?</p>
        </div>
      )}

      {messages.map((message, index) => (
        <ChatMessage
          key={message.id}
          message={message}
          messageMeta={messageMeta}
          streamingAssistantId={streamingAssistantId}
          isLastMessage={index === messages.length - 1}
          onEditMessage={onEditMessage}
          onRegenerate={onRegenerate}
          onFeedback={onFeedback}
          feedbackState={feedbackState}
          onUndo={onUndo}
        />
      ))}

      {isLoading && !streamingAssistantId && (
        <div className={`${styles['message']} ${styles['assistant']}`}>
          <div className={styles['message-content']}>
            <p className={styles['loading-text']}>
              {outputMode === 'stream' && streamStatusText ? `${streamStatusText}...` : 'Thinking...'}
            </p>
          </div>
        </div>
      )}

      <div ref={messagesEndRef as React.RefObject<HTMLDivElement>} />
    </div>
  )
}
