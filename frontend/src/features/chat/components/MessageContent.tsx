/* 助手消息 Markdown/数学公式渲染组件 */
import { memo, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import 'katex/dist/katex.min.css'
import 'highlight.js/styles/github-dark.min.css'
import styles from './MessageContent.module.css'

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

  const remarkPlugins = useMemo(() => [remarkMath, remarkGfm], [])
  const rehypePlugins = useMemo(() => [rehypeKatex, rehypeHighlight], [])

  return (
    <div className={styles['markdown-body']}>
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

export const MessageContent = memo(MessageContentInner)
