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

  // 流式期间且无内容时显示加载点动画
  if (isStreaming && !content) {
    return (
      <div className={styles.messageContainer}>
        <div className={styles.streamingIndicator}>
          <span className={styles.dot}></span>
          <span className={styles.dot}></span>
          <span className={styles.dot}></span>
        </div>
      </div>
    )
  }

  // 助手消息：流式期间和非流式均使用 Markdown 渲染
  // 流式期间通过 streaming prop 启用容错预处理和节流渲染
  return (
    <div className={styles.messageContainer}>
      {content && (
        <Suspense fallback={<div className={styles['markdown-body']}><span style={{ whiteSpace: 'pre-wrap' }}>{content}</span></div>}>
          <AssistantMarkdownContent content={content} streaming={isStreaming} />
        </Suspense>
      )}
    </div>
  )
}

export const MessageContent = memo(MessageContentInner)
