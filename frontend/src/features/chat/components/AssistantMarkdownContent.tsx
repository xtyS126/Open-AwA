import { memo, useEffect, useMemo, useRef, useState, useCallback } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import rehypeHighlight from 'rehype-highlight'
import 'katex/dist/katex.min.css'
import 'highlight.js/styles/github-dark.min.css'
import styles from './MessageContent.module.css'

interface AssistantMarkdownContentProps {
  content: string
  /** 是否处于流式输出状态；流式期间启用容错预处理和节流渲染 */
  streaming?: boolean
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
        decoding="async"
        style={{ cursor: 'pointer', maxWidth: '100%', borderRadius: '8px', margin: '8px 0' }}
      />
      {showLightbox && (
        <div className={styles['image-lightbox-overlay']} onClick={handleClose}>
          <div className={styles['image-lightbox-content']}>
            <img src={src} alt={alt || '图片'} loading="lazy" decoding="async" style={{ maxWidth: '90vw', maxHeight: '90vh', objectFit: 'contain' }} />
            <button className={styles['image-lightbox-close']} onClick={handleClose} aria-label="关闭图片预览">×</button>
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
  const base64ImageRegex = /(?<!\(|!\[)(data:image\/[a-zA-Z+.-]+;base64,[A-Za-z0-9+/=]+)(?!\))/g
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
  const urlImageRegex = /(?<!\(|!\[)(https?:\/\/[^\s"'<>]+\.(?:png|jpg|jpeg|gif|webp|bmp)(?:\?[^\s"'<>]*)?)(?!\))/gi
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

/**
 * 流式期间容错预处理：自动闭合未完成的 Markdown 语法结构。
 * 纯函数，无副作用。
 *
 * 处理范围：
 * - 未闭合代码块（```/~~~ 围栏出现次数为奇数）→ 末尾追加闭合围栏
 * - 未闭合块级公式（$$ 出现次数为奇数）→ 末尾追加 $$
 * - 未闭合强调标记（** __ * _）→ 末尾追加对应闭合符号
 *
 * 注意事项：
 * - 行内公式 $...$ 不自动闭合（避免误判），由 KaTeX 自行处理
 * - 代码块内的内容跳过统计，避免误判
 * - 双字符标记（** __）先于单字符标记（* _）统计，避免重复计数
 * - 代码块未闭合时仅闭合代码块，其他标记交给渲染器显示原文
 */
function preprocessStreamingContent(content: string): string {
  if (!content) return content

  const lines = content.split('\n')
  let inCodeBlock = false
  let codeBlockFenceCount = 0

  // 代码块外的标记统计
  let dollarDollarCount = 0
  let doubleStarCount = 0
  let doubleUnderscoreCount = 0
  let singleStarCount = 0
  let singleUnderscoreCount = 0

  for (const line of lines) {
    // 检测代码块围栏（``` 或 ~~~），支持行首空白
    const fenceMatch = line.match(/^\s*(```+|~~~+)/)
    if (fenceMatch) {
      inCodeBlock = !inCodeBlock
      codeBlockFenceCount++
      continue
    }

    // 跳过代码块内的行
    if (inCodeBlock) continue

    // 统计 $$（块级公式分隔符）
    let dollarPos = 0
    while ((dollarPos = line.indexOf('$$', dollarPos)) !== -1) {
      dollarDollarCount++
      dollarPos += 2
    }

    // 统计 **（双星号强调）
    let doubleStarPos = 0
    while ((doubleStarPos = line.indexOf('**', doubleStarPos)) !== -1) {
      doubleStarCount++
      doubleStarPos += 2
    }

    // 统计 __（双下划线强调）
    let doubleUnderPos = 0
    while ((doubleUnderPos = line.indexOf('__', doubleUnderPos)) !== -1) {
      doubleUnderscoreCount++
      doubleUnderPos += 2
    }

    // 统计 *（单星号，先剔除 ** 避免重复计数）
    const withoutDoubleStar = line.replace(/\*\*/g, '')
    let singleStarPos = 0
    while ((singleStarPos = withoutDoubleStar.indexOf('*', singleStarPos)) !== -1) {
      singleStarCount++
      singleStarPos += 1
    }

    // 统计 _（单下划线，先剔除 __ 避免重复计数）
    const withoutDoubleUnder = line.replace(/__/g, '')
    let singleUnderPos = 0
    while ((singleUnderPos = withoutDoubleUnder.indexOf('_', singleUnderPos)) !== -1) {
      singleUnderscoreCount++
      singleUnderPos += 1
    }
  }

  let result = content

  // 代码块未闭合：仅闭合代码块，其他标记交给渲染器显示原文
  if (codeBlockFenceCount % 2 === 1) {
    result += '\n```\n'
    return result
  }

  // 闭合未完成的块级公式
  if (dollarDollarCount % 2 === 1) {
    result += '\n$$\n'
  }

  // 闭合未完成的双字符强调标记（先 ** 后 __）
  if (doubleStarCount % 2 === 1) {
    result += '**'
  }
  if (doubleUnderscoreCount % 2 === 1) {
    result += '__'
  }

  // 闭合未完成的单字符强调标记（先 * 后 _）
  if (singleStarCount % 2 === 1) {
    result += '*'
  }
  if (singleUnderscoreCount % 2 === 1) {
    result += '_'
  }

  return result
}

function AssistantMarkdownContentInner({ content, streaming = false }: AssistantMarkdownContentProps) {
  const remarkPlugins = useMemo(() => [remarkMath, remarkGfm], [])
  const rehypePlugins = useMemo(() => [rehypeKatex, rehypeHighlight], [])

  // 流式节流相关 refs：记录上次渲染的内容和时间戳
  const lastRenderedContentRef = useRef<string>('')
  const lastRenderTimeRef = useRef<number>(0)
  const [throttledContent, setThrottledContent] = useState<string>(content)

  // 节流逻辑：流式期间限制重渲染频率，避免高频解析 Markdown/KaTeX
  // 触发条件（任一）：streaming=false / 内容变化 >= 50 字符 / 距上次渲染 >= 200ms
  // 监听 streaming 变化可确保流式结束瞬间立即用完整内容渲染一次
  useEffect(() => {
    if (!streaming) {
      // 非流式：始终使用最新内容（包括流式结束的瞬间）
      setThrottledContent(content)
      lastRenderedContentRef.current = content
      lastRenderTimeRef.current = Date.now()
      return
    }

    // 流式期间：内容变化 >= 50 字符 或 距上次渲染 >= 200ms 时才更新
    const now = Date.now()
    const contentDiff = Math.abs(content.length - lastRenderedContentRef.current.length)
    const timeDiff = now - lastRenderTimeRef.current

    if (contentDiff >= 50 || timeDiff >= 200) {
      setThrottledContent(content)
      lastRenderedContentRef.current = content
      lastRenderTimeRef.current = now
    }
  }, [content, streaming])

  // 实际渲染内容：流式时经过容错预处理，再统一经过图片预处理
  const processedContent = useMemo(() => {
    const rawContent = streaming
      ? preprocessStreamingContent(throttledContent)
      : throttledContent
    return preprocessImageContent(rawContent)
  }, [throttledContent, streaming])

  const imageComponents = useMemo<Components>(() => ({
    img: (props) => {
      // 提取 react-markdown 注入的 props，忽略其余 ExtraProps 字段
      const { src, alt } = props as { src?: string; alt?: string }
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

// 使用 React.memo 浅比较 props（content 字符串 + streaming 布尔），避免父组件重渲染时本组件被无谓重渲染
export default memo(AssistantMarkdownContentInner)
