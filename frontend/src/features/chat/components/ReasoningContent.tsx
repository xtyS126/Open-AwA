import React, { useState, useRef, useEffect, useCallback } from 'react'
import styles from './ReasoningContent.module.css'

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
  // Use localStorage to initialize state
  const getInitialState = () => {
    try {
      const saved = localStorage.getItem(`reasoning_expanded_${messageId}`)
      if (saved !== null) {
        return JSON.parse(saved)
      }
    } catch (e) {
      console.warn('Failed to read localStorage', e)
    }
    // Default: expanded when streaming, collapsed otherwise
    return isStreaming
  }

  const [isExpanded, setIsExpanded] = useState<boolean>(getInitialState)
  const [userManuallyTouched, setUserManuallyTouched] = useState<boolean>(false)
  const contentRef = useRef<HTMLDivElement>(null)
  const prevStreamingRef = useRef(isStreaming)

  const toggleExpand = useCallback(() => {
    const newState = !isExpanded
    setIsExpanded(newState)
    setUserManuallyTouched(true)
    try {
      localStorage.setItem(`reasoning_expanded_${messageId}`, JSON.stringify(newState))
    } catch (e) {
      console.warn('Failed to save localStorage', e)
    }
  }, [isExpanded, messageId])

  // Handle auto-collapse when streaming ends
  useEffect(() => {
    if (prevStreamingRef.current === true && isStreaming === false) {
      // Stream just finished, auto collapse if user didn't manually override
      if (!userManuallyTouched) {
        setIsExpanded(false)
      }
    }
    prevStreamingRef.current = isStreaming
  }, [isStreaming, userManuallyTouched])

  // Handle auto-scroll to bottom when streaming
  useEffect(() => {
    if (isStreaming && isExpanded && contentRef.current) {
      // Use requestAnimationFrame or setTimeout to ensure DOM is updated before scrolling
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
        tabIndex={0}
        aria-expanded={isExpanded}
      >
        <span className={`${styles.icon} ${isExpanded ? styles.expanded : ''}`}>
          ▶
        </span>
        <span>思考过程 {isStreaming ? '(思考中...)' : ''}</span>
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
