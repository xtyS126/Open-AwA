import { memo, useMemo, useState, useCallback } from 'react'
import { Pencil, Copy, RefreshCw, ThumbsUp, ThumbsDown, Check } from 'lucide-react'
import type {
  AssistantExecutionMeta,
  AssistantMessageSegment,
  ChatMessage as ChatMessageType,
} from '@/features/chat/types'
import { buildSegmentsFromLegacyMessage } from '@/features/chat/utils/assistantSegments'
import type { AssistantThoughtSegment as AssistantThoughtSegmentData, AssistantReplySegment } from '@/features/chat/types'
import { MessageContent } from './MessageContent'
import AssistantThoughtSegment from './AssistantThoughtSegment'
import styles from '../ChatPage.module.css'

interface ChatMessageProps {
  message: ChatMessageType
  messageMeta: Record<string, AssistantExecutionMeta>
  streamingAssistantId: string | null
  isLastMessage: boolean
  onEditMessage?: (content: string) => void
  /** 重新生成回调（仅助手消息） */
  onRegenerate?: (messageId: string) => void
  /** 反馈回调（点赞/点踩） */
  onFeedback?: (messageId: string, rating: 1 | -1) => void
  /** 各消息的反馈状态，messageId -> 1(赞) | -1(踩) */
  feedbackState?: Record<string, 1 | -1 | undefined>
  onUndo?: (operationId: string) => Promise<void>
}

type GroupedSegment = 
  | { kind: 'thought_group', id: string, segments: AssistantThoughtSegmentData[] }
  | AssistantReplySegment

function groupAssistantSegments(segments: AssistantMessageSegment[]): GroupedSegment[] {
  const result: GroupedSegment[] = []
  let currentThoughtGroup: AssistantThoughtSegmentData[] | null = null

  for (const segment of segments) {
    if (segment.kind === 'thought') {
      if (!currentThoughtGroup) {
        currentThoughtGroup = []
        result.push({ kind: 'thought_group', id: `group-${segment.id}`, segments: currentThoughtGroup })
      }
      currentThoughtGroup.push(segment)
    } else {
      currentThoughtGroup = null
      result.push(segment)
    }
  }

  return result
}

function getAssistantSegments(
  message: ChatMessageType,
  meta: AssistantExecutionMeta | undefined
): AssistantMessageSegment[] {
  if (message.segments && message.segments.length > 0) {
    return message.segments
  }

  const fallbackMeta = meta || {
    steps: [],
    toolEvents: message.toolEvents || [],
  }

  return buildSegmentsFromLegacyMessage({
    content: message.content,
    reasoningContent: message.reasoning_content,
    meta: fallbackMeta,
  })
}

function ChatMessageInner({ message, messageMeta, streamingAssistantId, isLastMessage, onEditMessage, onRegenerate, onFeedback, feedbackState, onUndo }: ChatMessageProps) {
  const isCurrentlyStreaming = streamingAssistantId === message.id && isLastMessage && message.role === 'assistant'
  const [copied, setCopied] = useState(false)

  // 仅依赖当前消息的 meta，避免整个 messageMeta 变化导致所有消息组件重计算
  const currentMeta = messageMeta[message.id]
  const assistantSegments = useMemo(() => {
    if (message.role !== 'assistant') return []
    return getAssistantSegments(message, currentMeta)
  }, [message, currentMeta])

  const groupedSegments = useMemo(() => {
    return groupAssistantSegments(assistantSegments)
  }, [assistantSegments])

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(message.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard API 不可用时的静默处理 */
    }
  }, [message.content])

  return (
    <div className={`${styles['message']} ${message.role === 'user' ? styles['user'] : styles['assistant']} ${message.isError ? styles['messageError'] : ''}`}>
      <div className={styles['message-content']}>
        {message.role === 'user' && (
          <>
            <MessageContent content={message.content} role={message.role} isStreaming={isCurrentlyStreaming} />
            {!isCurrentlyStreaming && onEditMessage && (
              <button className={styles['editBtn']} onClick={() => onEditMessage(message.content)} title="编辑消息">
                <Pencil size={14} />
              </button>
            )}
          </>
        )}
        {message.role === 'assistant' && groupedSegments.map((group) => (
          group.kind === 'thought_group' ? (
            <AssistantThoughtSegment
              key={group.id}
              segments={group.segments}
              isStreaming={isCurrentlyStreaming && group.segments.some(s => s.status === 'running')}
              onUndo={onUndo}
            />
          ) : (
            <MessageContent
              key={group.id}
              content={group.content}
              role={message.role}
              isStreaming={isCurrentlyStreaming}
            />
          )
        ))}
        {message.role === 'assistant' && !isCurrentlyStreaming && !message.isError && (
          <div className={styles['actionsBar']}>
            <button className={styles['actionBtn']} onClick={handleCopy} title="复制">
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
            {onRegenerate && (
              <button className={styles['actionBtn']} onClick={() => onRegenerate(message.id)} title="重新生成">
                <RefreshCw size={14} />
              </button>
            )}
            {onFeedback && (
              <>
                <button
                  className={`${styles['actionBtn']} ${feedbackState?.[message.id] === 1 ? styles['actionBtnActive'] : ''}`}
                  onClick={() => onFeedback(message.id, 1)}
                  disabled={feedbackState?.[message.id] === -1}
                  title="点赞"
                >
                  <ThumbsUp size={14} />
                </button>
                <button
                  className={`${styles['actionBtn']} ${feedbackState?.[message.id] === -1 ? styles['actionBtnActive'] : ''}`}
                  onClick={() => onFeedback(message.id, -1)}
                  disabled={feedbackState?.[message.id] === 1}
                  title="点踩"
                >
                  <ThumbsDown size={14} />
                </button>
              </>
            )}
            {/* 生成耗时显示 */}
            {messageMeta[message.id]?.usage?.duration_ms != null && (
              <span className={styles['durationBadge']}>
                {messageMeta[message.id].usage!.duration_ms! >= 1000
                  ? `${(messageMeta[message.id].usage!.duration_ms! / 1000).toFixed(1)}s`
                  : `${messageMeta[message.id].usage!.duration_ms!}ms`}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export const ChatMessage = memo(ChatMessageInner)
