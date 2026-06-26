import { memo } from 'react'
import type { AssistantThoughtSegment as AssistantThoughtSegmentData, TaskStatus } from '@/features/chat/types'
import { formatUsageCost, formatUsageTokens, getTaskTitle, getVisibleSubagentTools } from '@/features/chat/utils/executionMeta'
import { ThinkingProcess } from './ThinkingProcess'
import InlineToolCallCard from './InlineToolCallCard'
import { SubagentExecutionContainer } from './SubagentExecutionContainer'
import styles from './AssistantThoughtSegment.module.css'

interface AssistantThoughtSegmentProps {
  segments: AssistantThoughtSegmentData[]
  isStreaming: boolean
  onUndo?: (operationId: string) => Promise<void>
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

/** 获取步骤状态对应的圆点样式类名 */
function getStepDotClass(status: TaskStatus): string {
  switch (status) {
    case 'completed':
      return styles.stepDotCompleted
    case 'running':
      return styles.stepDotRunning
    case 'error':
      return styles.stepDotError
    default:
      return styles.stepDotPending
  }
}

/** 树形节点：圆点 + 连接线 + 内容 */
function TreeNode({
  dotClassName,
  children,
  className,
}: {
  dotClassName?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={`${styles.treeNode} ${className || ''}`}>
      <div className={`${styles.treeNodeDot} ${dotClassName || ''}`} />
      <div className={styles.treeNodeLine} />
      <div className={styles.treeNodeContent}>
        {children}
      </div>
    </div>
  )
}

function AssistantThoughtSegmentInner({ segments, isStreaming, onUndo }: AssistantThoughtSegmentProps) {
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
        {segments.map((segment) => {
          const subagentTools = getVisibleSubagentTools(segment.toolEvents)
          const regularTools = segment.toolEvents.filter((tool) => tool.kind !== 'subagent')

          return (
            <div key={segment.id} className={styles.segmentGroup}>
              {/* 意图节点：顶层 */}
              {segment.intent && (
                <TreeNode className={styles.intentNode}>
                  <span className={styles.intentText}>{segment.intent}</span>
                </TreeNode>
              )}

              {/* 推理节点：意图的子节点 */}
              {segment.reasoningContent && (
                <div className={styles.subTree}>
                  <TreeNode className={styles.reasoningNode}>
                    <div className={styles.reasoningText}>
                      {segment.reasoningContent}
                    </div>
                  </TreeNode>
                </div>
              )}

              {/* 执行步骤：推理的子节点 */}
              {segment.steps.length > 0 && (
                <div className={styles.subTree}>
                  <TreeNode className={styles.sectionNode}>
                    <span className={styles.sectionTitle}>执行步骤</span>
                  </TreeNode>
                  <div className={styles.subTree}>
                    {segment.steps.map((step) => (
                      <TreeNode
                        key={`${step.step}-${step.action}`}
                        className={styles.stepNode}
                        dotClassName={getStepDotClass(step.status)}
                      >
                        <div className={styles.stepContent}>
                          <span className={`${styles.stepStatus} ${styles[`status-${step.status}`]}`}>
                            {getStatusText(step.status)}
                          </span>
                          <span className={styles.stepTitle}>{getTaskTitle(step)}</span>
                          {step.summary && <span className={styles.stepSummary}>{step.summary}</span>}
                        </div>
                      </TreeNode>
                    ))}
                  </div>
                </div>
              )}

              {/* 子代理执行：步骤的嵌套子节点 */}
              {subagentTools.length > 0 && (
                <div className={styles.subTree}>
                  <TreeNode className={styles.sectionNode}>
                    <span className={styles.sectionTitle}>子代理执行</span>
                  </TreeNode>
                  <div className={styles.subTree}>
                    {subagentTools.map((tool) => (
                      <TreeNode
                        key={tool.id}
                        className={styles.subagentNode}
                      >
                        <div className={styles.subagentContent}>
                          <SubagentExecutionContainer
                            id={tool.id}
                            name={tool.name}
                            status={tool.status === 'error' ? 'error' : tool.status === 'completed' ? 'completed' : 'running'}
                            statusLabel={tool.status === 'completed' ? '已完成' : tool.status === 'error' ? '异常' : '运行中'}
                            logs={tool.subagent?.logs || tool.detail || ''}
                            truncated={Boolean(tool.subagent?.truncated)}
                            depth={1}
                          />
                        </div>
                      </TreeNode>
                    ))}
                  </div>
                </div>
              )}

              {/* 工具调用：叶子节点 */}
              {regularTools.length > 0 && (
                <div className={styles.subTree}>
                  <TreeNode className={styles.sectionNode}>
                    <span className={styles.sectionTitle}>工具调用</span>
                  </TreeNode>
                  <div className={styles.subTree}>
                    {regularTools.map((tool) => (
                      <TreeNode
                        key={tool.id}
                        className={styles.toolNode}
                      >
                        <div className={styles.toolContent}>
                          <InlineToolCallCard
                            tool={tool}
                            onUndo={onUndo}
                          />
                        </div>
                      </TreeNode>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )
        })}

        {/* 用量信息：底部节点 */}
        {usage && (
          <div className={styles.subTree}>
            <TreeNode className={styles.sectionNode}>
              <span className={styles.sectionTitle}>用量信息</span>
            </TreeNode>
            <div className={styles.subTree}>
              <TreeNode className={styles.usageNode}>
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
              </TreeNode>
            </div>
          </div>
        )}
      </ThinkingProcess>
    </div>
  )
}

export const AssistantThoughtSegment = memo(AssistantThoughtSegmentInner)

export default AssistantThoughtSegment
