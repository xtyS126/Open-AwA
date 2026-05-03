import React, { useState, useRef, useEffect, useCallback } from 'react'
import styles from './ReasoningContent.module.css'

const reasoningExpansionMemory = new Map<string, boolean>()

interface ReasoningContentProps {
  messageId: string
  content: string
  isStreaming: boolean
}

export const ReasoningContent: React.FC<ReasoningContentProps> = ({
  messageId,
  content,
  isStreaming,
}) => {
  const getInitialState = () => {
    const saved = reasoningExpansionMemory.get(messageId)
    if (typeof saved === 'boolean') {
      return saved
    }
    return isStreaming
  }

  const [isExpanded, setIsExpanded] = useState<boolean>(getInitialState)
  const contentRef = useRef<HTMLDivElement>(null)
  const hasManualOverrideRef = useRef(reasoningExpansionMemory.has(messageId))
  
  const streamingStartRef = useRef<number | null>(null)
  const [elapsedTime, setElapsedTime] = useState<number>(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    const saved = reasoningExpansionMemory.get(messageId)
    hasManualOverrideRef.current = typeof saved === 'boolean'
    setIsExpanded(typeof saved === 'boolean' ? saved : isStreaming)
  }, [messageId, isStreaming])

  useEffect(() => {
    if (hasManualOverrideRef.current) {
      return
    }
    setIsExpanded(isStreaming)
  }, [isStreaming])

  useEffect(() => {
    if (isStreaming && streamingStartRef.current === null) {
      streamingStartRef.current = Date.now()
      timerRef.current = setInterval(() => {
        if (streamingStartRef.current) {
          setElapsedTime(Math.floor((Date.now() - streamingStartRef.current) / 1000))
        }
      }, 1000)
    }
    if (!isStreaming && streamingStartRef.current !== null) {
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
    reasoningExpansionMemory.set(messageId, newState)
    hasManualOverrideRef.current = true
  }, [isExpanded, messageId])

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

  return (
    <div className={styles.container}>
      <div
        className={styles.header}
        onClick={toggleExpand}
        role="button"
      >
        <span className={`${styles.icon} ${isExpanded ? styles.expanded : ''}`}>
          🧠
        </span>
        <span className={styles.headerText}>
          {isStreaming ? '思考过程 (思考中...)' : '思考过程'}
        </span>
        {elapsedTime > 0 && <span className={styles.elapsed}>{elapsedTime}s</span>}
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
