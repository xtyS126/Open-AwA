/**
 * 消息列表组件 — 使用 react-virtuoso 虚拟滚动优化长对话渲染性能。
 * 超过 100 条消息时自动启用虚拟化，保证滚动流畅。
 */
import { memo, useCallback, useRef } from 'react'
import { Virtuoso, type VirtuosoHandle } from 'react-virtuoso'
import type { ChatMessage as ChatMessageType, AssistantExecutionMeta } from '@/features/chat/types'
import { useI18nStore } from '@/i18n'
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

/** 虚拟滚动阈值：消息数超过此值时启用 Virtuoso */
const VIRTUAL_THRESHOLD = 100

export const MessageList = memo(function MessageList({
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
  const { t } = useI18nStore()
  const virtuosoRef = useRef<VirtuosoHandle>(null)

  /** 流式输出时自动跟随最新内容 */
  const followOutput = useCallback(() => {
    if (streamingAssistantId) return 'smooth'
    return false
  }, [streamingAssistantId])

  /** 渲染单条消息（供 Virtuoso itemContent 和普通渲染共用）。
   *  注：每次 messages.length 变化时函数引用自然更新，Virtuoso 会重新调用 itemContent，
   *  这是符合预期的行为，无需通过 useCallback 缓存。 */
  const renderMessage = (index: number, message: ChatMessageType) => {
    return (
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
    )
  }

  /* 空状态 */
  if (messages.length === 0 && !isLoading) {
    return (
      <div className={styles['chat-messages']} role="log" aria-live="polite" aria-label="消息列表">
        <div className={styles['chat-empty']}>
          <p>{t('chat.empty')}</p>
        </div>
      </div>
    )
  }

  /* 加载指示器组件 */
  const LoadingFooter = isLoading && !streamingAssistantId ? (
    <div className={`${styles['message']} ${styles['assistant']}`}>
      <div className={styles['message-content']}>
        <p className={styles['loading-text']}>
          {outputMode === 'stream' && streamStatusText ? `${streamStatusText}...` : 'Thinking...'}
        </p>
      </div>
    </div>
  ) : null

  /* 消息超过阈值使用虚拟滚动，否则普通渲染 */
  if (messages.length >= VIRTUAL_THRESHOLD) {
    return (
      <div className={styles['chat-messages']} role="log" aria-live="polite" aria-label="消息列表">
        <Virtuoso
          ref={virtuosoRef}
          data={messages}
          totalCount={messages.length}
          itemContent={renderMessage}
          followOutput={followOutput}
          initialTopMostItemIndex={messages.length - 1}
          components={{
            Footer: () => <>{LoadingFooter}<div ref={messagesEndRef as React.RefObject<HTMLDivElement>} /></>,
          }}
          style={{ height: '100%' }}
        />
      </div>
    )
  }

  /* 普通渲染（消息较少时避免 Virtuoso 的开销） */
  return (
    <div className={styles['chat-messages']} role="log" aria-live="polite" aria-label="消息列表">
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

      {LoadingFooter}

      <div ref={messagesEndRef as React.RefObject<HTMLDivElement>} />
    </div>
  )
})
