import { FormEvent, useCallback, useEffect, useState } from 'react'

import {
  ScheduledTask,
  ScheduledTaskCreatePayload,
  ScheduledTaskExecution,
  scheduledTasksAPI,
} from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'

import styles from './ScheduledTasksPage.module.css'

function getErrorMessage(error: unknown, fallback: string): string {
  const maybeError = error as { response?: { data?: { detail?: string } } }
  const detail = maybeError?.response?.data?.detail
  return typeof detail === 'string' && detail.trim() ? detail : fallback
}

function padNumber(value: number): string {
  return String(value).padStart(2, '0')
}

function toLocalDateTimeInput(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return ''
  }

  return `${date.getFullYear()}-${padNumber(date.getMonth() + 1)}-${padNumber(date.getDate())}T${padNumber(date.getHours())}:${padNumber(date.getMinutes())}`
}

function createDefaultScheduledAt(): string {
  const date = new Date(Date.now() + 10 * 60 * 1000)
  date.setSeconds(0, 0)
  return toLocalDateTimeInput(date.toISOString())
}

function toIsoString(value: string): string {
  return new Date(value).toISOString()
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return '未记录'
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

function formatStatusLabel(status: string): string {
  const mapping: Record<string, string> = {
    pending: '待执行',
    running: '执行中',
    completed: '已完成',
    failed: '执行失败',
    cancelled: '已取消',
  }
  return mapping[status] || status
}

function ScheduledTasksPage() {
  const [tasks, setTasks] = useState<ScheduledTask[]>([])
  const [executions, setExecutions] = useState<ScheduledTaskExecution[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [pendingTaskId, setPendingTaskId] = useState<number | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [editingTaskId, setEditingTaskId] = useState<number | null>(null)
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')
  const [scheduledAt, setScheduledAt] = useState(createDefaultScheduledAt)
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')

  const resetForm = useCallback(() => {
    setEditingTaskId(null)
    setTitle('')
    setPrompt('')
    setScheduledAt(createDefaultScheduledAt())
    setProvider('')
    setModel('')
  }, [])

  const loadData = useCallback(async () => {
    setLoading(true)
    setLoadError(null)

    try {
      const [tasksResponse, executionsResponse] = await Promise.all([
        scheduledTasksAPI.getAll({ limit: 100 }),
        scheduledTasksAPI.getExecutions({ limit: 50 }),
      ])

      setTasks(tasksResponse.data)
      setExecutions(executionsResponse.data)
    } catch (error) {
      appLogger.error({
        event: 'scheduled_tasks_page_load_failed',
        module: 'scheduled_tasks',
        action: 'load',
        status: 'failure',
        message: '加载定时任务页面数据失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      setTasks([])
      setExecutions([])
      setLoadError(getErrorMessage(error, '加载定时任务数据失败，请稍后重试'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const handleEdit = (task: ScheduledTask) => {
    setEditingTaskId(task.id)
    setActionError(null)
    setTitle(task.title)
    setPrompt(task.prompt)
    setScheduledAt(toLocalDateTimeInput(task.scheduled_at))
    setProvider(task.provider || '')
    setModel(task.model || '')
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setActionError(null)

    const payload: ScheduledTaskCreatePayload = {
      title,
      prompt,
      scheduled_at: toIsoString(scheduledAt),
      provider: provider.trim() || null,
      model: model.trim() || null,
    }

    try {
      if (editingTaskId !== null) {
        await scheduledTasksAPI.update(editingTaskId, payload)
      } else {
        await scheduledTasksAPI.create(payload)
      }

      resetForm()
      await loadData()
    } catch (error) {
      appLogger.error({
        event: 'scheduled_task_submit_failed',
        module: 'scheduled_tasks',
        action: editingTaskId !== null ? 'update' : 'create',
        status: 'failure',
        message: '提交定时任务失败',
        extra: {
          scheduled_task_id: editingTaskId,
          error: error instanceof Error ? error.message : String(error),
        },
      })
      setActionError(getErrorMessage(error, '提交定时任务失败，请检查输入后重试'))
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancelTask = async (taskId: number) => {
    if (!confirm('确定要取消这个定时任务吗？')) {
      return
    }

    setPendingTaskId(taskId)
    setActionError(null)
    try {
      await scheduledTasksAPI.cancel(taskId)
      if (editingTaskId === taskId) {
        resetForm()
      }
      await loadData()
    } catch (error) {
      appLogger.error({
        event: 'scheduled_task_cancel_failed',
        module: 'scheduled_tasks',
        action: 'cancel',
        status: 'failure',
        message: '取消定时任务失败',
        extra: { scheduled_task_id: taskId, error: error instanceof Error ? error.message : String(error) },
      })
      setActionError(getErrorMessage(error, '取消定时任务失败，请稍后重试'))
    } finally {
      setPendingTaskId(null)
    }
  }

  const pendingCount = tasks.filter((task) => task.status === 'pending').length
  const completedCount = tasks.filter((task) => task.status === 'completed').length
  const failedCount = tasks.filter((task) => task.status === 'failed').length

  if (loading) {
    return <div className={styles['loading']}>正在加载定时任务...</div>
  }

  return (
    <div className={styles['scheduled-tasks-page']}>
      <section className={styles['hero']}>
        <div>
          <p className={styles['eyebrow']}>一次性 AI 调度</p>
          <h1>定时任务</h1>
          <p className={styles['hero-copy']}>
            为 AI 设置一个明确触发时间和提示词。任务执行结果只沉淀在当前页面历史中，不进入聊天会话与记忆链路。
          </p>
        </div>
        <div className={styles['hero-actions']}>
          <button className="btn btn-secondary" onClick={() => void loadData()} disabled={loading || submitting}>
            刷新数据
          </button>
        </div>
      </section>

      {loadError && <div className={styles['status-message-error']}>{loadError}</div>}
      {actionError && <div className={styles['status-message-error']}>{actionError}</div>}

      <section className={styles['stats-grid']}>
        <article className={styles['stat-card']}>
          <span>待执行</span>
          <strong>{pendingCount}</strong>
          <p>队列中等待触发的任务数量</p>
        </article>
        <article className={styles['stat-card']}>
          <span>已完成</span>
          <strong>{completedCount}</strong>
          <p>执行成功并已写入历史的任务数量</p>
        </article>
        <article className={styles['stat-card']}>
          <span>失败任务</span>
          <strong>{failedCount}</strong>
          <p>需要调整提示词或模型配置的任务数量</p>
        </article>
        <article className={styles['stat-card']}>
          <span>历史记录</span>
          <strong>{executions.length}</strong>
          <p>最近 50 条执行结果快照</p>
        </article>
      </section>

      <div className={styles['content-grid']}>
        <section className={`${styles['panel']} ${styles['form-panel']}`}>
          <div className={styles['panel-header']}>
            <div>
              <h2>{editingTaskId !== null ? '编辑任务' : '创建任务'}</h2>
              <p>首版仅支持单次执行和聊天提示词。</p>
            </div>
            {editingTaskId !== null && (
              <button className="btn btn-ghost" onClick={resetForm} type="button">
                取消编辑
              </button>
            )}
          </div>

          <form className={styles['task-form']} onSubmit={(event) => void handleSubmit(event)}>
            <label className={styles['form-field']}>
              <span>任务标题</span>
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="例如：周报总结提醒"
                maxLength={200}
                required
              />
            </label>

            <label className={styles['form-field']}>
              <span>执行时间</span>
              <input
                type="datetime-local"
                value={scheduledAt}
                onChange={(event) => setScheduledAt(event.target.value)}
                required
              />
            </label>

            <label className={styles['form-field']}>
              <span>提示词</span>
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="输入需要 AI 在指定时间执行的内容"
                rows={8}
                required
              />
            </label>

            <div className={styles['inline-fields']}>
              <label className={styles['form-field']}>
                <span>Provider</span>
                <input
                  value={provider}
                  onChange={(event) => setProvider(event.target.value)}
                  placeholder="留空时使用默认配置"
                />
              </label>

              <label className={styles['form-field']}>
                <span>Model</span>
                <input
                  value={model}
                  onChange={(event) => setModel(event.target.value)}
                  placeholder="留空时使用默认模型"
                />
              </label>
            </div>

            <div className={styles['form-actions']}>
              <button className="btn btn-primary" type="submit" disabled={submitting}>
                {submitting ? '提交中...' : editingTaskId !== null ? '保存修改' : '创建任务'}
              </button>
            </div>
          </form>
        </section>

        <section className={`${styles['panel']} ${styles['queue-panel']}`}>
          <div className={styles['panel-header']}>
            <div>
              <h2>任务队列</h2>
              <p>查看当前任务状态，并对待执行任务进行调整。</p>
            </div>
          </div>

          <div className={styles['task-list']}>
            {tasks.length === 0 ? (
              <div className={styles['empty-state']}>
                <p>当前还没有定时任务。</p>
              </div>
            ) : (
              tasks.map((task) => (
                <article key={task.id} className={styles['task-card']}>
                  <div className={styles['task-card-top']}>
                    <div>
                      <h3>{task.title}</h3>
                      <p>{formatDateTime(task.scheduled_at)}</p>
                    </div>
                    <span className={`${styles['status-badge']} ${styles[`status-${task.status}`] || ''}`}>
                      {formatStatusLabel(task.status)}
                    </span>
                  </div>

                  <p className={styles['task-prompt']}>{task.prompt}</p>

                  <div className={styles['task-meta']}>
                    <span>Provider: {task.provider || '默认'}</span>
                    <span>Model: {task.model || '默认'}</span>
                  </div>

                  {task.last_error_message && (
                    <div className={styles['task-error']}>{task.last_error_message}</div>
                  )}

                  {task.status === 'pending' && (
                    <div className={styles['task-actions']}>
                      <button className="btn btn-secondary" onClick={() => handleEdit(task)} type="button">
                        编辑
                      </button>
                      <button
                        className="btn btn-ghost"
                        onClick={() => void handleCancelTask(task.id)}
                        disabled={pendingTaskId === task.id}
                        type="button"
                      >
                        {pendingTaskId === task.id ? '处理中...' : '取消'}
                      </button>
                    </div>
                  )}
                </article>
              ))
            )}
          </div>
        </section>
      </div>

      <section className={`${styles['panel']} ${styles['history-panel']}`}>
        <div className={styles['panel-header']}>
          <div>
            <h2>执行历史</h2>
            <p>只展示定时任务自己的执行结果，不与聊天记录混用。</p>
          </div>
        </div>

        <div className={styles['history-list']}>
          {executions.length === 0 ? (
            <div className={styles['empty-state']}>
              <p>暂无执行历史，任务触发后会在这里展示结果。</p>
            </div>
          ) : (
            executions.map((execution) => (
              <article key={execution.id} className={styles['history-card']}>
                <div className={styles['history-card-top']}>
                  <div>
                    <h3>{execution.task_title}</h3>
                    <p>
                      计划时间 {formatDateTime(execution.scheduled_for)} · 开始时间 {formatDateTime(execution.started_at)}
                    </p>
                  </div>
                  <span className={`${styles['status-badge']} ${styles[`status-${execution.status}`] || ''}`}>
                    {formatStatusLabel(execution.status)}
                  </span>
                </div>

                <div className={styles['history-meta']}>
                  <span>Provider: {execution.provider || '默认'}</span>
                  <span>Model: {execution.model || '默认'}</span>
                </div>

                <div className={styles['history-block']}>
                  <strong>提示词</strong>
                  <p>{execution.prompt}</p>
                </div>

                <div className={styles['history-block']}>
                  <strong>{execution.error_message ? '错误信息' : '执行结果'}</strong>
                  <p>{execution.error_message || execution.response || '暂无输出'}</p>
                </div>
              </article>
            ))
          )}
        </div>
      </section>
    </div>
  )
}

export default ScheduledTasksPage