/**
 * 任务执行日志查看器组件。
 * 展示任务执行历史的时间线视图，支持按任务筛选和状态过滤。
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Clock,
  CheckCircle,
  XCircle,
  Loader,
  Filter,
  ChevronDown,
  ChevronUp,
  History,
} from 'lucide-react'
import { ScheduledTaskExecution, scheduledTasksAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import styles from './TaskLogViewer.module.css'

interface Props {
  taskId?: number
  compact?: boolean
}

function formatDateTime(value: string | null): string {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(date)
}

function formatDuration(started: string, completed: string | null): string {
  if (!completed) return '执行中...'
  const start = new Date(started).getTime()
  const end = new Date(completed).getTime()
  const ms = end - start
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
}

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'running':
      return <Loader size={16} className={styles['icon-running']} />
    case 'completed':
      return <CheckCircle size={16} className={styles['icon-completed']} />
    case 'failed':
      return <XCircle size={16} className={styles['icon-failed']} />
    default:
      return <Clock size={16} className={styles['icon-pending']} />
  }
}

function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    running: '执行中',
    completed: '已完成',
    failed: '失败',
  }
  return (
    <span className={`${styles['badge']} ${styles[`badge-${status}`] || ''}`}>
      {labels[status] || status}
    </span>
  )
}

export default function TaskLogViewer({ taskId, compact }: Props) {
  const [executions, setExecutions] = useState<ScheduledTaskExecution[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [statusFilter, setStatusFilter] = useState<string>('')

  const loadExecutions = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const params: { task_id?: number; limit?: number } = { limit: 50 }
      if (taskId) params.task_id = taskId
      const res = await scheduledTasksAPI.getExecutions(params)
      setExecutions(res.data)
    } catch (err) {
      appLogger.error({
        event: 'execution_logs_load_failed',
        module: 'scheduled_tasks',
        action: 'load_execution_logs',
        status: 'failure',
        message: '加载执行日志失败',
        extra: { error: err instanceof Error ? err.message : String(err) },
      })
      setError('加载执行日志失败')
    } finally {
      setLoading(false)
    }
  }, [taskId])

  useEffect(() => {
    loadExecutions()
  }, [loadExecutions])

  const filtered = statusFilter
    ? executions.filter((e) => e.status === statusFilter)
    : executions

  if (loading) {
    return (
      <div className={styles['loading']}>
        <Clock size={18} className={styles['spin']} />
        加载执行日志...
      </div>
    )
  }

  if (error) {
    return (
      <div className={styles['error']}>
        <span>{error}</span>
        <button className="btn btn-ghost" onClick={loadExecutions} type="button">
          重试
        </button>
      </div>
    )
  }

  if (!compact) {
    return (
      <div className={styles['container']}>
        <div className={styles['header']}>
          <div className={styles['header-left']}>
            <History size={18} />
            <h3>执行历史</h3>
            <span className={styles['count']}>{executions.length}</span>
          </div>
          <div className={styles['header-right']}>
            <Filter size={14} />
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className={styles['filter-select']}
            >
              <option value="">全部状态</option>
              <option value="running">执行中</option>
              <option value="completed">已完成</option>
              <option value="failed">失败</option>
            </select>
            <button className="btn btn-ghost" onClick={loadExecutions} type="button">
              刷新
            </button>
          </div>
        </div>

        {filtered.length === 0 ? (
          <div className={styles['empty']}>
            <History size={24} />
            <p>暂无执行记录</p>
            <span>任务触发后会在这里展示执行日志</span>
          </div>
        ) : (
          <div className={styles['timeline']}>
            {filtered.map((exec) => (
              <div key={exec.id} className={styles['timeline-item']}>
                <div className={styles['timeline-dot']}>
                  <StatusIcon status={exec.status} />
                </div>
                <div className={styles['timeline-content']}>
                  <div className={styles['exec-header']}>
                    <div className={styles['exec-title']}>
                      <span className={styles['exec-task-title']}>
                        {exec.task_title}
                      </span>
                      <StatusBadge status={exec.status} />
                    </div>
                    <span className={styles['exec-duration']}>
                      {formatDuration(exec.started_at, exec.completed_at)}
                    </span>
                  </div>

                  <div className={styles['exec-meta']}>
                    <span>计划: {formatDateTime(exec.scheduled_for)}</span>
                    <span>开始: {formatDateTime(exec.started_at)}</span>
                    {exec.completed_at && (
                      <span>完成: {formatDateTime(exec.completed_at)}</span>
                    )}
                  </div>

                  {/* 提示词 */}
                  {exec.prompt && (
                    <details className={styles['exec-details']}>
                      <summary>提示词</summary>
                      <pre>{exec.prompt}</pre>
                    </details>
                  )}

                  {/* 结果/错误 */}
                  {(exec.response || exec.error_message) && (
                    <div className={styles['exec-result']}>
                      {exec.error_message ? (
                        <div className={styles['result-error']}>
                          <strong>错误信息</strong>
                          <pre>{exec.error_message}</pre>
                        </div>
                      ) : (
                        exec.response && (
                          <details className={styles['exec-details']}>
                            <summary>执行结果</summary>
                            <pre>
                              {(() => {
                                try {
                                  const parsed = JSON.parse(exec.response)
                                  return JSON.stringify(parsed, null, 2)
                                } catch {
                                  return exec.response
                                }
                              })()}
                            </pre>
                          </details>
                        )
                      )}
                    </div>
                  )}

                  {/* 元数据 */}
                  {exec.execution_metadata &&
                    Object.keys(exec.execution_metadata).length > 0 && (
                      <div className={styles['exec-metadata']}>
                        {exec.execution_metadata.task_type != null && (
                          <span className={styles['meta-tag']}>
                            类型: {String(exec.execution_metadata.task_type) === 'plugin_command' ? '插件命令' : 'AI任务'}
                          </span>
                        )}
                        {exec.execution_metadata.plugin_name != null && (
                          <span className={styles['meta-tag']}>
                            插件: {String(exec.execution_metadata.plugin_name)}
                          </span>
                        )}
                        {exec.execution_metadata.command_name != null && (
                          <span className={styles['meta-tag']}>
                            命令: {String(exec.execution_metadata.command_name)}
                          </span>
                        )}
                      </div>
                    )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    )
  }

  // 紧凑模式：只显示最近5条
  const recent = executions.slice(0, 5)
  return (
    <div className={styles['compact']}>
      <div className={styles['compact-header']}>
        <History size={16} />
        <span>最近执行</span>
        <span className={styles['compact-count']}>{executions.length}</span>
      </div>
      {recent.length === 0 ? (
        <p className={styles['compact-empty']}>暂无记录</p>
      ) : (
        recent.map((exec) => (
          <div key={exec.id} className={styles['compact-item']}>
            <StatusIcon status={exec.status} />
            <span className={styles['compact-title']}>{exec.task_title}</span>
            <StatusBadge status={exec.status} />
            <span className={styles['compact-time']}>
              {formatDateTime(exec.started_at)}
            </span>
            <button
              type="button"
              className={styles['compact-expand']}
              onClick={() =>
                setExpandedId(expandedId === exec.id ? null : exec.id)
              }
            >
              {expandedId === exec.id ? (
                <ChevronUp size={14} />
              ) : (
                <ChevronDown size={14} />
              )}
            </button>
            {expandedId === exec.id && (
              <div className={styles['compact-detail']}>
                {exec.error_message ? (
                  <pre className={styles['error-pre']}>{exec.error_message}</pre>
                ) : (
                  <pre>{exec.response || '暂无输出'}</pre>
                )}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  )
}
