/**
 * 消息列表组件 — 使用 react-virtuoso 虚拟滚动优化长对话渲染性能。
 * 超过 15 条消息时自动启用虚拟化，保证滚动流畅。
 */
import { memo, useCallback, useRef } from 'react'
import { Virtuoso, type VirtuosoHandle } from 'react-virtuoso'
import { ArrowDown } from 'lucide-react'
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
  /** 滚动容器 ref callback，由 useChatAutoScroll 提供，用于绑定滚动事件 */
  scrollContainerRef?: (el: HTMLElement | null) => void
  /** 是否显示"跳到最新"悬浮按钮 */
  showJumpToLatest?: boolean
  /** 点击"跳到最新"按钮的回调 */
  onJumpToLatest?: () => void
  /** 未读新消息数量（用于按钮文案，可选） */
  unreadCount?: number
  onEditMessage?: (content: string) => void
  onRegenerate?: (messageId: string) => void
  onFeedback?: (messageId: string, rating: 1 | -1) => void
  feedbackState?: Record<string, 1 | -1 | undefined>
  onUndo?: (operationId: string) => Promise<void>
}

/** 虚拟滚动阈值：消息数达到此值时启用 Virtuoso，避免长对话下 DOM 节点过多 */
const VIRTUAL_THRESHOLD = 15

export const MessageList = memo(function MessageList({
  messages,
  messageMeta,
  streamingAssistantId,
  isLoading,
  outputMode,
  streamStatusText,
  messagesEndRef,
  scrollContainerRef,
  showJumpToLatest = false,
  onJumpToLatest,
  unreadCount = 0,
  onEditMessage,
  onRegenerate,
  onFeedback,
  feedbackState,
  onUndo,
}: MessageListProps) {
  // 使用选择器精确订阅，避免整个 store 变化触发重渲染
  const t = useI18nStore(s => s.t)
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

  /** "跳到最新"悬浮按钮：当用户远离底部且有新内容到达时显示 */
  const jumpToLatestButton = showJumpToLatest && onJumpToLatest ? (
    <button
      type="button"
      className={styles['jumpToLatestBtn']}
      onClick={onJumpToLatest}
      aria-label={t('chat.jumpToLatest')}
    >
      <ArrowDown size={14} />
      <span>{unreadCount > 0 ? t('chat.unreadMessages', { count: String(unreadCount) }) : t('chat.jumpToLatest')}</span>
    </button>
  ) : null

  /* 空状态 */
  if (messages.length === 0 && !isLoading) {
    return (
      <div className={styles['chat-messages']} role="log" aria-live="polite" aria-label="消息列表" ref={scrollContainerRef}>
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
      <div className={styles['chat-messages']} role="log" aria-live="polite" aria-label="消息列表" ref={scrollContainerRef}>
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
        {jumpToLatestButton}
      </div>
    )
  }

  /* 普通渲染（消息较少时避免 Virtuoso 的开销） */
  return (
    <div className={styles['chat-messages']} role="log" aria-live="polite" aria-label="消息列表" ref={scrollContainerRef}>
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

      {jumpToLatestButton}
    </div>
  )
})
