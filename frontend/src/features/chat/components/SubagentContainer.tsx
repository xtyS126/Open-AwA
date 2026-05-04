import React, { useEffect, useRef, useState } from 'react'
import ansiHTML from 'ansi-html-community'
import { useToast } from '@/shared/components/Toast'
import type { SubagentStep } from './useSubagentManager'
import styles from './SubagentContainer.module.css'

interface SubagentContainerProps {
  agentId: string
  name: string
  status: 'running' | 'completed' | 'error'
  content: string
  exitCode?: number
  steps: SubagentStep[]
  defaultExpanded?: boolean
}

const STEP_ICONS: Record<SubagentStep['type'], string> = {
  thought: '🧠',
  file_read: '👓',
  search: '🔍',
  tool_call: '🔧',
  generic: '📋',
}

export const SubagentContainer: React.FC<SubagentContainerProps> = ({
  agentId: _agentId,
  name,
  status,
  content,
  exitCode,
  steps,
  defaultExpanded = true,
}) => {
  const contentRef = useRef<HTMLDivElement>(null)
  const [internalStatus, setInternalStatus] = useState(status)
  const timerRef = useRef<number | null>(null)
  const [processedContent, setProcessedContent] = useState('')
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)
  const { addToast } = useToast()

  useEffect(() => {
    if (status === 'error' || (exitCode !== 0 && exitCode !== undefined)) {
      setInternalStatus('error')
      addToast(`Subagent ${name} 执行失败`, 'error')
    } else {
      setInternalStatus(status)
    }
  }, [status, exitCode, name, addToast])

  useEffect(() => {
    if (internalStatus === 'running') {
      if (timerRef.current) {
        window.clearTimeout(timerRef.current)
      }
      timerRef.current = window.setTimeout(() => {
        setInternalStatus('error')
        addToast(`Subagent ${name} 执行失败`, 'error')
      }, 30000)
    }

    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current)
    }
  }, [content, internalStatus, name, addToast])

  useEffect(() => {
    let currentContent = content
    if (currentContent.length > 50000) {
      const truncateLength = Math.floor(currentContent.length * 0.1)
      currentContent = '日志过长，已截断\n' + currentContent.slice(truncateLength)
    }

    setProcessedContent(ansiHTML(currentContent.replace(/</g, '&lt;').replace(/>/g, '&gt;')))
  }, [content])

  useEffect(() => {
    if (contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight
    }
  }, [processedContent])

  const toggleExpand = () => {
    setIsExpanded((prev) => !prev)
  }

  return (
    <div className={styles.container}>
      <div className={styles.header} onClick={toggleExpand}>
        <div className={`${styles.statusLight} ${styles[internalStatus]}`} />
        <span className={styles.title}>{name}</span>
        <span className={`${styles.chevron} ${isExpanded ? styles.chevronExpanded : ''}`}>
          ▶
        </span>
      </div>

      <div className={`${styles.treeBody} ${isExpanded ? styles.treeBodyExpanded : ''}`}>
        <div className={styles.treeLine} />
        {steps.map((step, index) => (
          <div key={`${step.timestamp}-${index}`} className={styles.stepNode}>
            <div className={styles.stepConnector} />
            <span className={styles.stepIcon}>{STEP_ICONS[step.type] || STEP_ICONS.generic}</span>
            <span className={styles.stepLabel}>{step.label}</span>
          </div>
        ))}
      </div>

      {content.length > 0 && (
        <div
          className={`${styles.contentArea} ${isExpanded ? styles.contentAreaVisible : ''}`}
          ref={contentRef}
          dangerouslySetInnerHTML={{ __html: processedContent }}
        />
      )}
    </div>
  )
}
