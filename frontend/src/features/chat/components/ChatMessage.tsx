import { memo, useMemo } from 'react'
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

function ChatMessageInner({ message, messageMeta, streamingAssistantId, isLastMessage }: ChatMessageProps) {
  const isCurrentlyStreaming = streamingAssistantId === message.id && isLastMessage && message.role === 'assistant'

  const assistantSegments = useMemo(() => {
    if (message.role !== 'assistant') return []
    return getAssistantSegments(message, messageMeta[message.id])
  }, [message, messageMeta])

  const groupedSegments = useMemo(() => {
    return groupAssistantSegments(assistantSegments)
  }, [assistantSegments])

  return (
    <div className={`${styles['message']} ${message.role === 'user' ? styles['user'] : styles['assistant']}`}>
      <div className={styles['message-content']}>
        {message.role === 'user' && (
          <MessageContent content={message.content} role={message.role} isStreaming={isCurrentlyStreaming} />
        )}
        {message.role === 'assistant' && groupedSegments.map((group) => (
          group.kind === 'thought_group' ? (
            <AssistantThoughtSegment
              key={group.id}
              segments={group.segments}
              isStreaming={isCurrentlyStreaming && group.segments.some(s => s.status === 'running')}
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
      </div>
    </div>
  )
}

export const ChatMessage = memo(ChatMessageInner)
