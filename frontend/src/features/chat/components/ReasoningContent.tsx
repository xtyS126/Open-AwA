import React, { useState, useRef, useEffect, useCallback } from 'react'
import { appLogger } from '@/shared/utils/logger'
import styles from './ReasoningContent.module.css'

interface ReasoningContentProps {
  messageId: string
  content: string
  isStreaming: boolean
}

// 估算 token 数量（中文约 1-2 字符/token，英文约 4 字符/token，取折中值）
function estimateTokenCount(text: string): number {
  if (!text) return 0
  const chineseChars = (text.match(/[\u4e00-\u9fff]/g) || []).length
  const otherChars = text.length - chineseChars
  return Math.ceil(chineseChars / 1.5 + otherChars / 4)
}

export const ReasoningContent: React.FC<ReasoningContentProps> = ({
  messageId,
  content,
  isStreaming,
}) => {
  // 从 localStorage 读取初始展开状态
  const getInitialState = () => {
    try {
      const saved = localStorage.getItem(`reasoning_expanded_${messageId}`)
      if (saved !== null) {
        return JSON.parse(saved)
      }
    } catch (e) {
      appLogger.warning({ event: 'localstorage_read_failed', message: 'Failed to read localStorage', module: 'reasoning' })
    }
    // 默认：流式时展开，否则收起
    return isStreaming
  }

  const [isExpanded, setIsExpanded] = useState<boolean>(getInitialState)
  const [userManuallyTouched, setUserManuallyTouched] = useState<boolean>(false)
  const [copySuccess, setCopySuccess] = useState<boolean>(false)
  const contentRef = useRef<HTMLDivElement>(null)
  const prevStreamingRef = useRef(isStreaming)
  // 记录推理开始时间
  const streamingStartRef = useRef<number | null>(null)
  const [elapsedTime, setElapsedTime] = useState<number>(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 推理计时逻辑
  useEffect(() => {
    if (isStreaming && streamingStartRef.current === null) {
      // 推理开始
      streamingStartRef.current = Date.now()
      timerRef.current = setInterval(() => {
        if (streamingStartRef.current) {
          setElapsedTime(Math.floor((Date.now() - streamingStartRef.current) / 1000))
        }
      }, 1000)
    }
    if (!isStreaming && streamingStartRef.current !== null) {
      // 推理结束，记录最终耗时
      setElapsedTime(Math.floor((Date.now() - streamingStartRef.current) / 1000))
      streamingStartRef.current = null
      if (timerRef.current) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current)
      }
    }
  }, [isStreaming])

  const toggleExpand = useCallback(() => {
    const newState = !isExpanded
    setIsExpanded(newState)
    setUserManuallyTouched(true)
    try {
      localStorage.setItem(`reasoning_expanded_${messageId}`, JSON.stringify(newState))
    } catch (e) {
      appLogger.warning({ event: 'localstorage_save_failed', message: 'Failed to save localStorage', module: 'reasoning' })
    }
  }, [isExpanded, messageId])

  // 复制推理内容到剪贴板
  const handleCopy = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await navigator.clipboard.writeText(content)
      setCopySuccess(true)
      setTimeout(() => setCopySuccess(false), 2000)
    } catch (err) {
      appLogger.warning({ event: 'clipboard_copy_failed', message: 'Failed to copy reasoning content', module: 'reasoning' })
    }
  }, [content])

  // 流式结束后自动收起
  useEffect(() => {
    if (prevStreamingRef.current === true && isStreaming === false) {
      if (!userManuallyTouched) {
        setIsExpanded(false)
      }
    }
    prevStreamingRef.current = isStreaming
  }, [isStreaming, userManuallyTouched])

  // 流式时自动滚动到底部
  useEffect(() => {
    if (isStreaming && isExpanded && contentRef.current) {
      requestAnimationFrame(() => {
        if (contentRef.current) {
          const el = contentRef.current
          el.scrollTop = el.scrollHeight
        }
      })
    }
  }, [content, isStreaming, isExpanded])

  if (!content) return null

  const tokenCount = estimateTokenCount(content)

  return (
    <div className={styles.container}>
      <div
        className={styles.header}
        onClick={toggleExpand}
        role="button"
        tabIndex={0}
        aria-expanded={isExpanded}
      >
        <span className={`${styles.icon} ${isExpanded ? styles.expanded : ''}`}>
          ▶
        </span>
        <span className={styles.headerText}>
          思考过程 {isStreaming ? '(思考中...)' : ''}
        </span>
        <span className={styles.metaInfo}>
          {tokenCount > 0 && <span className={styles.tokenCount}>~{tokenCount} tokens</span>}
          {elapsedTime > 0 && <span className={styles.elapsed}>{elapsedTime}s</span>}
        </span>
        <button
          className={`${styles.copyBtn} ${copySuccess ? styles.copySuccess : ''}`}
          onClick={handleCopy}
          title="复制推理内容"
        >
          {copySuccess ? '已复制' : '复制'}
        </button>
      </div>
      <div
        ref={contentRef}
        className={`${styles.contentWrapper} ${isExpanded ? styles.expanded : ''}`}
        style={{ whiteSpace: 'pre-wrap' }}
      >
        {content}
      </div>
    </div>
  )
}
