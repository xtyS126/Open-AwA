/**
 * 工具调用内联展示卡片组件。
 *
 * 参考 OpenCode TUI 工具调用展示设计：
 * - 显示工具名称、状态图标和简短描述
 * - 可展开查看完整参数和执行结果
 * - 状态指示：pending（等待）/ running（执行中）/ completed（完成）/ error（错误）
 * - 支持不同类型工具的颜色区分
 */
import React, { useState } from 'react'
import styles from './ToolCallCard.module.css'

/** 工具调用状态 */
export type ToolCallStatus = 'pending' | 'running' | 'completed' | 'error'

/** 工具类别 */
export type ToolKind = 'tool' | 'plugin' | 'mcp' | 'task' | 'skill'

/** 工具调用数据 */
export interface ToolCallInfo {
  id: string
  kind: ToolKind
  name: string
  status: ToolCallStatus
  detail?: string
  output?: unknown
  executionTimeMs?: number
}

/** 各工具类别的颜色映射 */
const KIND_COLORS: Record<ToolKind, string> = {
  tool: '#4a9eff',
  plugin: '#a78bfa',
  mcp: '#f59e0b',
  task: '#10b981',
  skill: '#ec4899',
}

/** 各工具类别的中文标签 */
const KIND_LABELS: Record<ToolKind, string> = {
  tool: '工具',
  plugin: '插件',
  mcp: 'MCP',
  task: '任务',
  skill: '技能',
}

/** 状态图标映射 */
const STATUS_ICONS: Record<ToolCallStatus, string> = {
  pending: '⏳',   // ⏳
  running: '▶',   // ▶
  completed: '✅', // ✅
  error: '❌',     // ❌
}

interface ToolCallCardProps {
  toolCall: ToolCallInfo
  /** 默认是否展开 */
  defaultExpanded?: boolean
}

export const ToolCallCard: React.FC<ToolCallCardProps> = ({
  toolCall,
  defaultExpanded = false,
}) => {
  // 空值防御：若父组件传入 null/undefined 则返回 null
  if (!toolCall) {
    return null
  }

  const [expanded, setExpanded] = useState(defaultExpanded)
  const kind = toolCall.kind || 'tool'
  const color = KIND_COLORS[kind] || KIND_COLORS.tool
  const label = KIND_LABELS[kind] || '工具'
  const icon = STATUS_ICONS[toolCall.status] || ''

  const handleToggle = () => {
    setExpanded((prev) => !prev)
  }

  const formatOutput = (output: unknown): string => {
    if (output === undefined || output === null) return '(无输出)'
    if (typeof output === 'string') return output
    try {
      return JSON.stringify(output, null, 2)
    } catch (e) {
      console.error('ToolCallCard formatOutput: failed to serialize output', e)
      return String(output)
    }
  }

  return (
    <div
      className={`${styles.card} ${styles[toolCall.status]}`}
      style={{ borderLeftColor: color }}
    >
      {/* 摘要行：始终可见 */}
      <div className={styles.summary} onClick={handleToggle} role="button" tabIndex={0}>
        <span className={styles.icon}>{icon}</span>
        <span className={styles.kindBadge} style={{ backgroundColor: color }}>
          {label}
        </span>
        <span className={styles.name}>{toolCall.name}</span>
        {toolCall.detail && (
          <span className={styles.detail}>{toolCall.detail}</span>
        )}
        {toolCall.executionTimeMs != null && toolCall.status === 'completed' && (
          <span className={styles.time}>{toolCall.executionTimeMs}ms</span>
        )}
        <span className={styles.expandIcon}>{expanded ? '▼' : '▶'}</span>
      </div>

      {/* 展开详情 */}
      {expanded && (
        <div className={styles.details}>
          {toolCall.status === 'error' && toolCall.output !== null && toolCall.output !== undefined && (
            <div className={styles.errorSection}>
              <div className={styles.sectionTitle}>错误信息</div>
              <pre className={styles.errorContent}>
                {formatOutput(toolCall.output)}
              </pre>
            </div>
          )}
          {toolCall.status === 'completed' && toolCall.output !== null && toolCall.output !== undefined && (
            <div className={styles.outputSection}>
              <div className={styles.sectionTitle}>执行结果</div>
              <pre className={styles.outputContent}>
                {formatOutput(toolCall.output)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default ToolCallCard
