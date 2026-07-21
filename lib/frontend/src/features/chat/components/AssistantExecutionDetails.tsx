import { useMemo, useState } from 'react'
import type { AssistantExecutionMeta, TaskStatus, TaskStepMeta } from '@/features/chat/types'
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

function getStepIcon(action: string): string {
  switch (action) {
    case 'llm_chat':
    case 'llm_query':
    case 'llm_explain':
      return '◇'
    case 'execute_command':
      return '▷'
    case 'read_files':
      return '☷'
    case 'mcp_tool_call':
    case 'call_mcp_tool':
      return '⬡'
    default:
      return '○'
  }
}

function formatDurationMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}min`
}

function computeTotalDuration(meta: AssistantExecutionMeta): number | undefined {
  if (meta.totalDuration) return meta.totalDuration
  if (meta.usage?.duration_ms) return meta.usage.duration_ms

  const toolEvents = meta.toolEvents.filter(
    (t) => t.startedAt !== undefined && t.completedAt !== undefined
  )
  if (toolEvents.length === 0) return undefined

  const startTimes = toolEvents.map((t) => t.startedAt!).filter((v) => v > 0)
  const endTimes = toolEvents.map((t) => t.completedAt!).filter((v) => v > 0)
  if (startTimes.length === 0 || endTimes.length === 0) return undefined

  return Math.max(...endTimes) - Math.min(...startTimes)
}

function TimelineStepNode({ step }: { step: TaskStepMeta }) {
  return (
    <div className={`${styles['timeline-node']} ${styles[`node-${step.status}`]}`}>
      <div className={styles['timeline-node-marker']}>
        <div className={`${styles['node-dot']} ${styles[`dot-${step.status}`]}`}>
          {step.status === 'completed' && <span className={styles['node-check']}>✓</span>}
          {step.status === 'error' && <span className={styles['node-error-mark']}>✕</span>}
        </div>
        <div className={styles['node-line']} />
      </div>
      <div className={styles['timeline-node-content']}>
        <div className={styles['node-header']}>
          <span className={styles['node-icon']}>{getStepIcon(step.action)}</span>
          <span className={styles['node-title']}>{getTaskTitle(step)}</span>
          <span className={`${styles['node-status']} ${styles[`status-${step.status}`]}`}>
            {getStatusLabel(step.status)}
          </span>
        </div>
        {step.summary && <div className={styles['node-summary']}>{step.summary}</div>}
      </div>
    </div>
  )
}

function TimelineToolNode({ tool }: { tool: { id: string; kind: string; name: string; status: TaskStatus; detail?: string; startedAt?: number; completedAt?: number } }) {
  const duration = tool.startedAt && tool.completedAt ? tool.completedAt - tool.startedAt : undefined

  return (
    <div className={`${styles['timeline-node']} ${styles[`node-${tool.status}`]}`}>
      <div className={styles['timeline-node-marker']}>
        <div className={`${styles['node-dot']} ${styles[`dot-${tool.status}`]}`}>
          {tool.status === 'completed' && <span className={styles['node-check']}>✓</span>}
          {tool.status === 'error' && <span className={styles['node-error-mark']}>✕</span>}
        </div>
        <div className={styles['node-line']} />
      </div>
      <div className={styles['timeline-node-content']}>
        <div className={styles['node-header']}>
          <span className={styles['node-kind']}>{tool.kind}</span>
          <span className={styles['node-title']}>{tool.name}</span>
          <span className={`${styles['node-status']} ${styles[`status-${tool.status}`]}`}>
            {getStatusLabel(tool.status)}
          </span>
          {duration !== undefined && (
            <span className={styles['node-duration']}>{formatDurationMs(duration)}</span>
          )}
        </div>
        {tool.detail && <div className={styles['node-summary']}>{tool.detail}</div>}
      </div>
    </div>
  )
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
  }, [meta, isStreaming])

  const totalDuration = useMemo(() => computeTotalDuration(meta), [meta])

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
        {/* 总耗时统计条 */}
        {totalDuration !== undefined && (
          <div className={styles['duration-bar']}>
            <span className={styles['duration-label']}>总耗时</span>
            <span className={styles['duration-value']}>{formatDurationMs(totalDuration)}</span>
          </div>
        )}

        {meta.intent && (
          <section className={styles['section']}>
            <div className={styles['sectionTitle']}>意图</div>
            <div className={styles['intent']}>{meta.intent}</div>
          </section>
        )}

        {/* 时间线：执行步骤 */}
        {meta.steps.length > 0 && (
          <section className={styles['section']}>
            <div className={styles['sectionTitle']}>执行步骤</div>
            <div className={styles['timeline']}>
              {meta.steps.map((step) => (
                <TimelineStepNode key={`${step.step}-${step.action}`} step={step} />
              ))}
            </div>
          </section>
        )}

        {/* 时间线：工具调用 */}
        {meta.toolEvents.length > 0 && (
          <section className={styles['section']}>
            <div className={styles['sectionTitle']}>工具调用</div>
            <div className={styles['timeline']}>
              {meta.toolEvents.map((tool) => (
                <TimelineToolNode key={tool.id} tool={tool} />
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
