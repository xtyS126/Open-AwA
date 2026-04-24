import { useMemo, useState } from 'react'
import type { AssistantExecutionMeta, TaskStatus } from '@/features/chat/types'
import { formatUsageCost, formatUsageTokens, getTaskTitle } from '@/features/chat/utils/executionMeta'
import styles from './AssistantExecutionDetails.module.css'

const expansionMemory = new Map<string, boolean>()

interface AssistantExecutionDetailsProps {
  messageId: string
  meta: AssistantExecutionMeta
  isStreaming: boolean
}

function getStatusLabel(status: TaskStatus): string {
  switch (status) {
    case 'completed':
      return '已完成'
    case 'running':
      return '执行中'
    case 'error':
      return '失败'
    default:
      return '等待中'
  }
}

export function AssistantExecutionDetails({ messageId, meta, isStreaming }: AssistantExecutionDetailsProps) {
  const [isExpanded, setIsExpanded] = useState(() => expansionMemory.get(messageId) ?? false)

  const summaryText = useMemo(() => {
    const parts: string[] = []
    if (meta.steps.length > 0) {
      parts.push(`${meta.steps.length} 个步骤`)
    }
    if (meta.toolEvents.length > 0) {
      parts.push(`${meta.toolEvents.length} 次工具调用`)
    }
    if (meta.usage?.total_cost) {
      parts.push(formatUsageCost(meta.usage.total_cost, meta.usage.currency))
    }
    if (isStreaming) {
      parts.push('持续更新中')
    }
    return parts.join(' · ')
  }, [isStreaming, meta.steps.length, meta.toolEvents.length, meta.usage?.currency, meta.usage?.total_cost])

  const toggleExpanded = () => {
    const nextValue = !isExpanded
    setIsExpanded(nextValue)
    expansionMemory.set(messageId, nextValue)
  }

  return (
    <div className={styles['container']}>
      <button
        type="button"
        className={styles['header']}
        onClick={toggleExpanded}
        aria-expanded={isExpanded}
      >
        <span className={`${styles['chevron']} ${isExpanded ? styles['expanded'] : ''}`}>▶</span>
        <span className={styles['title']}>工具与执行详情</span>
        {summaryText && <span className={styles['summary']}>{summaryText}</span>}
      </button>

      <div className={`${styles['body']} ${isExpanded ? styles['body-expanded'] : ''}`}>
        {meta.intent && (
          <section className={styles['section']}>
            <div className={styles['sectionTitle']}>意图</div>
            <div className={styles['intent']}>{meta.intent}</div>
          </section>
        )}

        {meta.steps.length > 0 && (
          <section className={styles['section']}>
            <div className={styles['sectionTitle']}>执行步骤</div>
            <div className={styles['list']}>
              {meta.steps.map((step) => (
                <div key={`${step.step}-${step.action}`} className={styles['listItem']}>
                  <span className={`${styles['status']} ${styles[`status-${step.status}`]}`}>{getStatusLabel(step.status)}</span>
                  <div className={styles['listContent']}>
                    <div className={styles['itemTitle']}>{getTaskTitle(step)}</div>
                    {step.summary && <div className={styles['itemDetail']}>{step.summary}</div>}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {meta.toolEvents.length > 0 && (
          <section className={styles['section']}>
            <div className={styles['sectionTitle']}>工具调用</div>
            <div className={styles['list']}>
              {meta.toolEvents.map((tool) => (
                <div key={tool.id} className={styles['listItem']}>
                  <span className={`${styles['status']} ${styles[`status-${tool.status}`]}`}>{getStatusLabel(tool.status)}</span>
                  <div className={styles['listContent']}>
                    <div className={styles['itemTitleRow']}>
                      <span className={styles['kind']}>{tool.kind}</span>
                      <span className={styles['itemTitle']}>{tool.name}</span>
                    </div>
                    {tool.detail && <div className={styles['itemDetail']}>{tool.detail}</div>}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {meta.usage && (
          <section className={styles['section']}>
            <div className={styles['sectionTitle']}>用量信息</div>
            <div className={styles['usageGrid']}>
              <div className={styles['usageItem']}>
                <span className={styles['usageLabel']}>模型</span>
                <span className={styles['usageValue']}>{meta.usage.model || '未知'}</span>
              </div>
              <div className={styles['usageItem']}>
                <span className={styles['usageLabel']}>输入</span>
                <span className={styles['usageValue']}>{formatUsageTokens(meta.usage.input_tokens)}</span>
              </div>
              <div className={styles['usageItem']}>
                <span className={styles['usageLabel']}>输出</span>
                <span className={styles['usageValue']}>{formatUsageTokens(meta.usage.output_tokens)}</span>
              </div>
              <div className={styles['usageItem']}>
                <span className={styles['usageLabel']}>成本</span>
                <span className={styles['usageValue']}>{formatUsageCost(meta.usage.total_cost, meta.usage.currency)}</span>
              </div>
              {meta.usage.duration_ms && (
                <div className={styles['usageItem']}>
                  <span className={styles['usageLabel']}>耗时</span>
                  <span className={styles['usageValue']}>{meta.usage.duration_ms}ms</span>
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </div>
  )
}

export default AssistantExecutionDetails