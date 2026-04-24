/* 助手消息 Markdown/数学公式渲染组件 */
import { lazy, memo, Suspense } from 'react'
import styles from './MessageContent.module.css'

const AssistantMarkdownContent = lazy(() => import('./AssistantMarkdownContent'))

interface MessageContentProps {
  content: string
  role: 'user' | 'assistant'
}

/**
 * 消息内容渲染组件
 * - 用户消息：纯文本渲染
 * - 助手消息：Markdown + 数学公式 + 代码高亮
 */
function MessageContentInner({ content, role }: MessageContentProps) {
  // 用户消息保持纯文本渲染
  if (role === 'user') {
    return <span style={{ whiteSpace: 'pre-wrap' }}>{content}</span>
  }

  return (
    <Suspense fallback={<div className={styles['markdown-body']}><span style={{ whiteSpace: 'pre-wrap' }}>{content}</span></div>}>
      <AssistantMarkdownContent content={content} />
    </Suspense>
  )
}

export const MessageContent = memo(MessageContentInner)
