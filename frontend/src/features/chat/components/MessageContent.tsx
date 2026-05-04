/* 助手消息 Markdown/数学公式渲染组件 */
import { lazy, memo, Suspense } from 'react'
import styles from './MessageContent.module.css'

const AssistantMarkdownContent = lazy(() => import('./AssistantMarkdownContent'))

interface MessageContentProps {
  content: string
  role: 'user' | 'assistant'
  isStreaming?: boolean
}

function MessageContentInner({ content, role, isStreaming }: MessageContentProps) {
  if (role === 'user') {
    return <span style={{ whiteSpace: 'pre-wrap' }}>{content}</span>
  }

  return (
    <div className={styles.messageContainer}>
      {content && (
        <Suspense fallback={<div className={styles['markdown-body']}><span style={{ whiteSpace: 'pre-wrap' }}>{content}</span></div>}>
          <AssistantMarkdownContent content={content} />
        </Suspense>
      )}

      {isStreaming && !content && (
        <div className={styles.streamingIndicator}>
          <span className={styles.dot}></span>
          <span className={styles.dot}></span>
          <span className={styles.dot}></span>
        </div>
      )}
    </div>
  )
}

export const MessageContent = memo(MessageContentInner)
