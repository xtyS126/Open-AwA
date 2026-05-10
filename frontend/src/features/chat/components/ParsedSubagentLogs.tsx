import React, { useMemo } from 'react'
import type { ToolEventMeta } from '@/features/chat/types'
import { MessageContent } from './MessageContent'
import { ThinkingProcess } from './ThinkingProcess'
import InlineToolCallCard from './InlineToolCallCard'
import { parseSubagentLogs } from '../utils/logParser'
import styles from './ParsedSubagentLogs.module.css'

interface ParsedSubagentLogsProps {
  logs: string
}

// 根据工具名推断工具类型
function detectToolKind(name: string): string {
  if (!name) return 'tool'
  // MCP 工具格式：server_id/tool_name
  if (name.includes('/')) return 'mcp'
  return 'tool'
}

// 将任务状态字符串归一化为 ToolEventMeta.status
function normalizeSegmentStatus(raw: string | undefined): 'completed' | 'running' | 'error' | 'pending' {
  const s = (raw || '').trim().toLowerCase()
  if (s === 'completed' || s === 'done' || s === 'success' || s === '已完成') return 'completed'
  if (s === 'running' || s === 'in_progress' || s === '执行中' || s === '运行中') return 'running'
  if (s === 'error' || s === 'failed' || s === 'failure' || s === '失败') return 'error'
  return 'pending'
}

function getStatusLabel(status: string): string {
  switch (status) {
    case 'completed': return '已完成'
    case 'running': return '执行中'
    case 'error': return '失败'
    default: return '等待中'
  }
}

export const ParsedSubagentLogs: React.FC<ParsedSubagentLogsProps> = ({ logs }) => {
  const segments = useMemo(() => parseSubagentLogs(logs), [logs])

  if (!logs) {
    return <span className={styles.emptyHint}>暂无输出...</span>
  }

  return (
    <div className={styles.wrapper}>
      {segments.map((seg) => {
        // 思考块：使用与主代理相同的 ThinkingProcess 组件
        if (seg.type === 'think') {
          return (
            <ThinkingProcess
              key={seg.id}
              title="思考过程"
              defaultExpanded={!seg.isClosed}
              isThinking={!seg.isClosed}
            >
              <div className={styles.thinkContent}>
                {seg.content}
                {!seg.isClosed && (
                  <span
                    style={{
                      display: 'inline-block',
                      width: '8px',
                      height: '14px',
                      backgroundColor: 'currentColor',
                      marginLeft: '4px',
                      verticalAlign: 'middle',
                      animation: 'blink 1s step-end infinite',
                    }}
                  />
                )}
              </div>
            </ThinkingProcess>
          )
        }

        // 工具调用：使用与主代理相同的 InlineToolCallCard 组件
        if (seg.type === 'tool') {
          const toolMeta: ToolEventMeta = {
            id: seg.id,
            kind: detectToolKind(seg.toolName || ''),
            name: seg.toolName || seg.content,
            status: 'completed',
            detail: seg.toolDetail || seg.content,
          }
          return (
            <div key={seg.id} className={styles.toolRow}>
              <InlineToolCallCard tool={toolMeta} />
            </div>
          )
        }

        // 任务步骤
        if (seg.type === 'task') {
          const status = normalizeSegmentStatus(seg.taskStatus)
          return (
            <div key={seg.id} className={styles.taskRow}>
              <span className={`${styles.taskDot} ${styles[`taskDot-${status}`]}`} title={getStatusLabel(status)} />
              <span className={styles.taskLabel}>{seg.content}</span>
              {seg.taskStatus && (
                <span className={styles.taskStatus}>{getStatusLabel(status)}</span>
              )}
            </div>
          )
        }

        // 状态信息
        if (seg.type === 'status') {
          return (
            <div key={seg.id} className={styles.infoRow}>
              <span className={styles.infoIcon}>-</span>
              <span>{seg.content}</span>
            </div>
          )
        }

        // 计划信息
        if (seg.type === 'plan') {
          return (
            <div key={seg.id} className={styles.infoRow}>
              <span className={styles.infoIcon}>*</span>
              <span>{seg.content}</span>
            </div>
          )
        }

        // 错误信息
        if (seg.type === 'error') {
          return (
            <div key={seg.id} className={styles.errorRow}>
              {seg.content}
            </div>
          )
        }

        // 终端输出块
        if (seg.type === 'terminal') {
          return (
            <pre key={seg.id} className={styles.terminalBlock}>
              <code>
                {seg.content}
                {!seg.isClosed && <span className="cursor-blink">_</span>}
              </code>
            </pre>
          )
        }

        // 普通文本（Markdown 渲染）
        return (
          <div key={seg.id}>
            <MessageContent content={seg.content} role="assistant" />
          </div>
        )
      })}
    </div>
  )
}

