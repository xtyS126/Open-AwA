import { useMemo, useState, useCallback } from 'react'
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

/**
 * 自定义图片渲染组件 — 支持点击放大（灯箱效果）。
 */
function ImageWithLightbox({ src, alt }: { src?: string; alt?: string }) {
  const [showLightbox, setShowLightbox] = useState(false)

  const handleClick = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    setShowLightbox(true)
  }, [])

  const handleClose = useCallback(() => {
    setShowLightbox(false)
  }, [])

  return (
    <>
      <img
        src={src}
        alt={alt || '图片'}
        className={styles['markdown-image']}
        onClick={handleClick}
        loading="lazy"
        style={{ cursor: 'pointer', maxWidth: '100%', borderRadius: '8px', margin: '8px 0' }}
      />
      {showLightbox && (
        <div className={styles['image-lightbox-overlay']} onClick={handleClose}>
          <div className={styles['image-lightbox-content']}>
            <img src={src} alt={alt || '图片'} style={{ maxWidth: '90vw', maxHeight: '90vh', objectFit: 'contain' }} />
            <button className={styles['image-lightbox-close']} onClick={handleClose}>×</button>
            {alt && <p className={styles['image-lightbox-alt']}>{alt}</p>}
          </div>
        </div>
      )}
    </>
  )
}

/**
 * 预处理内容：检测并转换 base64 图片数据为可渲染的 img 标签。
 * 支持格式：data:image/...;base64,... 的独立 URL 字符串。
 */
function preprocessImageContent(content: string): string {
  // 检测独立的 base64 图片 URL（不在 markdown 图片语法中）
  const base64ImageRegex = /(?<!\(|\!\[)(data:image\/[a-zA-Z+.-]+;base64,[A-Za-z0-9+/=]+)(?!\))/g
  const hasMarkdownImage = /!\[.*?\]\(.*?\)/.test(content)

  // 如果内容中已有 markdown 图片语法，不做转换
  if (hasMarkdownImage && !base64ImageRegex.test(content.replace(/!\[.*?\]\(.*?\)/g, ''))) {
    return content
  }

  // 将独立的 base64 图片 URL 包装为 markdown 图片语法
  let processed = content
  let match: RegExpExecArray | null
  base64ImageRegex.lastIndex = 0

  // 收集所有匹配
  const matches: Array<{ index: number; text: string }> = []
  while ((match = base64ImageRegex.exec(content)) !== null) {
    matches.push({ index: match.index, text: match[0] })
  }

  // 从后往前替换，保持索引正确
  for (let i = matches.length - 1; i >= 0; i--) {
    const m = matches[i]
    const before = processed.substring(0, m.index)
    const after = processed.substring(m.index + m.text.length)
    processed = `${before}\n\n![生成的图片](${m.text})\n\n${after}`
  }

  // 同时检测纯 URL 图片链接（非 base64、非 markdown 包裹）
  const urlImageRegex = /(?<!\(|\!\[)(https?:\/\/[^\s"'<>]+\.(?:png|jpg|jpeg|gif|webp|bmp)(?:\?[^\s"'<>]*)?)(?!\))/gi
  if (!hasMarkdownImage) {
    let urlMatch: RegExpExecArray | null
    const urlMatches: Array<{ index: number; text: string }> = []
    while ((urlMatch = urlImageRegex.exec(content)) !== null) {
      // 跳过已在 markdown 图片语法中的 URL
      const before = content.substring(0, urlMatch.index)
      if (before.lastIndexOf('](') > before.lastIndexOf('\n') && before.lastIndexOf('](') > before.lastIndexOf('![')) {
        continue
      }
      urlMatches.push({ index: urlMatch.index, text: urlMatch[0] })
    }
    for (let i = urlMatches.length - 1; i >= 0; i--) {
      const m = urlMatches[i]
      const before = processed.substring(0, m.index)
      const after = processed.substring(m.index + m.text.length)
      processed = `${before}\n\n![生成的图片](${m.text})\n\n${after}`
    }
  }

  return processed
}

function AssistantMarkdownContent({ content }: AssistantMarkdownContentProps) {
  const remarkPlugins = useMemo(() => [remarkMath, remarkGfm], [])
  const rehypePlugins = useMemo(() => [rehypeKatex, rehypeHighlight], [])

  const processedContent = useMemo(() => preprocessImageContent(content), [content])

  const imageComponents = useMemo(() => ({
    img: ({ src, alt }: any) => {
      return <ImageWithLightbox src={src} alt={alt} />
    },
  }), [])

  return (
    <div className={styles['markdown-body']}>
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={imageComponents}
      >
        {processedContent}
      </ReactMarkdown>
    </div>
  )
}

export default AssistantMarkdownContent
