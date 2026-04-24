import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import 'katex/dist/katex.min.css'
import 'highlight.js/styles/github-dark.min.css'
import styles from './MessageContent.module.css'

interface AssistantMarkdownContentProps {
  content: string
}

function AssistantMarkdownContent({ content }: AssistantMarkdownContentProps) {
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

export default AssistantMarkdownContent