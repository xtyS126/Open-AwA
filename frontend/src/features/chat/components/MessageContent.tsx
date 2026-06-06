/* 助手消息 Markdown/数学公式渲染组件 — 使用 content-visibility 自动跳过离屏渲染 */
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

  // 流式期间纯文本展示，避免 Markdown/KaTeX/highlight 重复解析
  // 消息 finalize 后（isStreaming=false）才切换到富文本渲染
  if (isStreaming) {
    return (
      <div className={styles.messageContainer}>
        {content ? (
          <div className={styles['markdown-body']}>
            <span style={{ whiteSpace: 'pre-wrap' }}>{content}</span>
          </div>
        ) : (
          <div className={styles.streamingIndicator}>
            <span className={styles.dot}></span>
            <span className={styles.dot}></span>
            <span className={styles.dot}></span>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={styles.messageContainer}>
      {content && (
        <Suspense fallback={<div className={styles['markdown-body']}><span style={{ whiteSpace: 'pre-wrap' }}>{content}</span></div>}>
          <AssistantMarkdownContent content={content} />
        </Suspense>
      )}
    </div>
  )
}

export const MessageContent = memo(MessageContentInner)
