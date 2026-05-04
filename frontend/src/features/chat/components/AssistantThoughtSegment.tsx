import { memo } from 'react'
import type { AssistantThoughtSegment as AssistantThoughtSegmentData, TaskStatus } from '@/features/chat/types'
import { formatUsageCost, formatUsageTokens, getTaskTitle } from '@/features/chat/utils/executionMeta'
import { ThinkingProcess } from './ThinkingProcess'
import InlineToolCallCard from './InlineToolCallCard'
import styles from './AssistantThoughtSegment.module.css'

interface AssistantThoughtSegmentProps {
  segments: AssistantThoughtSegmentData[]
  isStreaming: boolean
}

function getStatusText(status: TaskStatus): string {
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

function AssistantThoughtSegmentInner({ segments, isStreaming }: AssistantThoughtSegmentProps) {
  const title = isStreaming ? '思维链（生成中）' : '思维链'

  const lastUsageSegment = [...segments].reverse().find(s => s.usage)
  const usage = lastUsageSegment?.usage

  return (
    <div className={styles.container}>
      <ThinkingProcess
        title={title}
        defaultExpanded={isStreaming}
        isThinking={isStreaming}
      >
        {segments.map((segment) => (
          <div key={segment.id} className={styles.segmentGroup}>
            {segment.intent && (
              <div className={styles.intent}>意图：{segment.intent}</div>
            )}

            {segment.reasoningContent && (
              <div className={styles.reasoningText}>
                {segment.reasoningContent}
              </div>
            )}

            {segment.steps.length > 0 && (
              <section className={styles.section}>
                <div className={styles.sectionTitle}>执行步骤</div>
                <div className={styles.stepList}>
                  {segment.steps.map((step) => (
                    <div key={`${step.step}-${step.action}`} className={styles.stepItem}>
                      <span className={`${styles.stepStatus} ${styles[`status-${step.status}`]}`}>
                        {getStatusText(step.status)}
                      </span>
                      <span className={styles.stepTitle}>{getTaskTitle(step)}</span>
                      {step.summary && <span className={styles.stepSummary}>{step.summary}</span>}
                    </div>
                  ))}
                </div>
              </section>
            )}

            {segment.toolEvents.length > 0 && (
              <section className={styles.section}>
                <div className={styles.sectionTitle}>工具调用</div>
                <div className={styles.toolList}>
                  {segment.toolEvents.map((tool) => (
                    <InlineToolCallCard
                      key={tool.id}
                      tool={tool}
                    />
                  ))}
                </div>
              </section>
            )}
          </div>
        ))}

        {usage && (
          <section className={styles.section}>
            <div className={styles.sectionTitle}>用量信息</div>
            <div className={styles.usageGrid}>
              <span className={styles.usageItem}>输入 {formatUsageTokens(usage.input_tokens)}</span>
              <span className={styles.usageItem}>输出 {formatUsageTokens(usage.output_tokens)}</span>
              <span className={styles.usageItem}>
                成本 {formatUsageCost(usage.total_cost, usage.currency)}
              </span>
              {usage.duration_ms && (
                <span className={styles.usageItem}>耗时 {usage.duration_ms}ms</span>
              )}
            </div>
          </section>
        )}
      </ThinkingProcess>
    </div>
  )
}

export const AssistantThoughtSegment = memo(AssistantThoughtSegmentInner)

export default AssistantThoughtSegment
