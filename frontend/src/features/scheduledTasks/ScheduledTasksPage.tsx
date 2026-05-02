/**
 * 定时任务管理页面组件。
 * 支持AI智能任务和插件命令任务两种类型，提供可视化的任务调度管理。
 */
import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react'
import {
  Clock,
  RefreshCw,
  CheckCircle,
  XCircle,
  Loader,
  Brain,
  Puzzle,
  List,
  LayoutGrid,
  Search,
  Trash2,
} from 'lucide-react'

import {
  ScheduledTask,
  ScheduledTaskCreatePayload,
  ScheduledTaskExecution,
  PluginCommandInfo,
  scheduledTasksAPI,
} from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'

import PluginCommandSelector from './components/PluginCommandSelector'
import CronExpressionBuilder from './components/CronExpressionBuilder'
import TaskParameterPanel from './components/TaskParameterPanel'
import TaskLogViewer from './components/TaskLogViewer'
import TaskTemplateManager from './components/TaskTemplateManager'

import styles from './ScheduledTasksPage.module.css'

/* ---- 工具函数 ---- */

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
  if (Number.isNaN(date.getTime())) return ''
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
  if (!value) return '未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
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

/* ---- 主组件 ---- */

type TabType = 'ai' | 'plugin'
type ViewMode = 'list' | 'grid'

export default function ScheduledTasksPage() {
  /* --- 通用状态 --- */
  const [activeTab, setActiveTab] = useState<TabType>('ai')
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [tasks, setTasks] = useState<ScheduledTask[]>([])
  const [, setExecutions] = useState<ScheduledTaskExecution[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [pendingTaskId, setPendingTaskId] = useState<number | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [selectedTasks, setSelectedTasks] = useState<Set<number>>(new Set())

  /* --- AI任务表单状态 --- */
  const [editingTaskId, setEditingTaskId] = useState<number | null>(null)
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')
  const [scheduledAt, setScheduledAt] = useState(createDefaultScheduledAt)
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')

  /* --- 每日执行状态 --- */
  const [isDaily, setIsDaily] = useState(false)
  const [dailyTime, setDailyTime] = useState('09:00')
  const [selectedWeekdays, setSelectedWeekdays] = useState<Set<number>>(
    new Set([0, 1, 2, 3, 4, 5, 6])
  )

  /* --- 插件命令任务状态 --- */
  const [selectedCommand, setSelectedCommand] = useState<PluginCommandInfo | null>(null)
  const [commandParams, setCommandParams] = useState<Record<string, unknown>>({})
  const [pluginTaskTitle, setPluginTaskTitle] = useState('')
  const [pluginScheduledAt, setPluginScheduledAt] = useState(createDefaultScheduledAt)
  const [pluginIsDaily, setPluginIsDaily] = useState(false)
  const [pluginCronExpr, setPluginCronExpr] = useState('')
  const [pluginWeekdays, setPluginWeekdays] = useState('')
  const [pluginDailyTime, setPluginDailyTime] = useState('09:00')

  /* --- 数据加载 --- */

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

  /* --- 表单重置 --- */

  const resetAiForm = useCallback(() => {
    setEditingTaskId(null)
    setTitle('')
    setPrompt('')
    setScheduledAt(createDefaultScheduledAt())
    setProvider('')
    setModel('')
    setIsDaily(false)
    setDailyTime('09:00')
    setSelectedWeekdays(new Set([0, 1, 2, 3, 4, 5, 6]))
  }, [])

  const resetPluginForm = useCallback(() => {
    setPluginTaskTitle('')
    setPluginScheduledAt(createDefaultScheduledAt())
    setPluginIsDaily(false)
    setPluginCronExpr('')
    setPluginWeekdays('')
    setPluginDailyTime('09:00')
    setSelectedCommand(null)
    setCommandParams({})
  }, [])

  /* --- AI任务提交 --- */

  const handleAiSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setActionError(null)

    const payload: ScheduledTaskCreatePayload = {
      title,
      prompt,
      scheduled_at: toIsoString(scheduledAt),
      provider: provider.trim() || null,
      model: model.trim() || null,
      is_daily: isDaily,
      task_type: 'ai_prompt',
    }

    if (isDaily) {
      const [h, m] = dailyTime.split(':')
      const dayStr = Array.from(selectedWeekdays).sort().join(',')
      payload.cron_expression = `${m} ${h} * * ${dayStr}`
      payload.daily_time = dailyTime
      payload.weekdays = dayStr
    }

    try {
      if (editingTaskId !== null) {
        await scheduledTasksAPI.update(editingTaskId, payload)
      } else {
        await scheduledTasksAPI.create(payload)
      }
      resetAiForm()
      await loadData()
    } catch (error) {
      appLogger.error({
        event: 'scheduled_task_submit_failed',
        module: 'scheduled_tasks',
        action: editingTaskId !== null ? 'update' : 'create',
        status: 'failure',
        message: '提交定时任务失败',
        extra: { scheduled_task_id: editingTaskId, error: error instanceof Error ? error.message : String(error) },
      })
      setActionError(getErrorMessage(error, '提交定时任务失败，请检查输入后重试'))
    } finally {
      setSubmitting(false)
    }
  }

  /* --- 插件命令任务提交 --- */

  const handlePluginSubmit = async () => {
    if (!selectedCommand || !pluginTaskTitle.trim()) {
      setActionError('请选择插件命令并填写任务标题')
      return
    }

    setSubmitting(true)
    setActionError(null)

    const payload: ScheduledTaskCreatePayload = {
      title: pluginTaskTitle.trim(),
      prompt: `执行插件 ${selectedCommand.plugin_name} 的 ${selectedCommand.command_name} 命令`,
      scheduled_at: toIsoString(pluginScheduledAt),
      task_type: 'plugin_command',
      plugin_name: selectedCommand.plugin_name,
      command_name: selectedCommand.command_name,
      command_params: commandParams,
      is_daily: pluginIsDaily,
    }

    if (pluginIsDaily) {
      payload.cron_expression = pluginCronExpr || null
      payload.daily_time = pluginDailyTime || null
      payload.weekdays = pluginWeekdays || null
    }

    try {
      await scheduledTasksAPI.create(payload)
      resetPluginForm()
      await loadData()
    } catch (error) {
      appLogger.error({
        event: 'plugin_task_submit_failed',
        module: 'scheduled_tasks',
        action: 'create',
        status: 'failure',
        message: '提交插件命令任务失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      setActionError(getErrorMessage(error, '提交插件命令任务失败'))
    } finally {
      setSubmitting(false)
    }
  }

  /* --- 通用操作 --- */

  const handleEdit = (task: ScheduledTask) => {
    if (task.task_type === 'plugin_command') {
      setActiveTab('plugin')
      setPluginTaskTitle(task.title)
      setPluginScheduledAt(toLocalDateTimeInput(task.scheduled_at))
      setPluginIsDaily(!!task.is_daily)
      setPluginDailyTime(task.daily_time || '09:00')
      setPluginWeekdays(task.weekdays || '')
      setPluginCronExpr(task.cron_expression || '')
      if (task.command_params) setCommandParams(task.command_params)
    } else {
      setActiveTab('ai')
      setEditingTaskId(task.id)
      setTitle(task.title)
      setPrompt(task.prompt)
      setScheduledAt(toLocalDateTimeInput(task.scheduled_at))
      setProvider(task.provider || '')
      setModel(task.model || '')
      setIsDaily(!!task.is_daily)
      setDailyTime(task.daily_time || '09:00')
      if (task.weekdays) {
        setSelectedWeekdays(new Set(task.weekdays.split(',').map(Number)))
      }
    }
  }

  const handleCancelTask = async (taskId: number) => {
    if (!confirm('确定要取消这个定时任务吗？')) return
    setPendingTaskId(taskId)
    setActionError(null)
    try {
      await scheduledTasksAPI.cancel(taskId)
      if (editingTaskId === taskId) resetAiForm()
      await loadData()
    } catch (error) {
      setActionError(getErrorMessage(error, '取消定时任务失败，请稍后重试'))
    } finally {
      setPendingTaskId(null)
    }
  }

  const handleBatchCancel = async () => {
    if (selectedTasks.size === 0) return
    if (!confirm(`确定要取消选中的 ${selectedTasks.size} 个任务吗？`)) return
    setActionError(null)
    let cancelled = 0
    for (const id of selectedTasks) {
      try {
        await scheduledTasksAPI.cancel(id)
        cancelled++
      } catch {
        /* 继续处理下一个 */
      }
    }
    setSelectedTasks(new Set())
    await loadData()
    if (cancelled > 0) {
      setActionError(null)
    }
  }

  const toggleTaskSelection = (taskId: number) => {
    setSelectedTasks((prev) => {
      const next = new Set(prev)
      if (next.has(taskId)) next.delete(taskId)
      else next.add(taskId)
      return next
    })
  }

  const handleTemplateLoad = (config: Record<string, unknown>) => {
    if (config.task_type === 'plugin_command') {
      setActiveTab('plugin')
      if (typeof config.title === 'string') setPluginTaskTitle(config.title)
      if (typeof config.plugin_name === 'string' && typeof config.command_name === 'string') {
        setSelectedCommand({
          plugin_name: config.plugin_name as string,
          plugin_version: '',
          plugin_description: '',
          command_name: config.command_name as string,
          command_description: '',
          command_method: config.command_name as string,
          parameters: {},
        })
      }
      if (config.command_params) setCommandParams(config.command_params as Record<string, unknown>)
      if (config.is_daily) setPluginIsDaily(true)
    } else {
      setActiveTab('ai')
      if (typeof config.title === 'string') setTitle(config.title)
      if (typeof config.prompt === 'string') setPrompt(config.prompt)
    }
  }

  /* --- 统计计算 --- */

  const stats = useMemo(() => {
    const pending = tasks.filter((t) => t.status === 'pending').length
    const running = tasks.filter((t) => t.status === 'running').length
    const completed = tasks.filter((t) => t.status === 'completed').length
    const failed = tasks.filter((t) => t.status === 'failed').length
    return { total: tasks.length, pending, running, completed, failed }
  }, [tasks])

  /* --- 筛选与搜索 --- */

  const filteredTasks = useMemo(() => {
    let result = tasks
    if (activeTab === 'ai') {
      result = result.filter((t) => t.task_type !== 'plugin_command')
    } else {
      result = result.filter((t) => t.task_type === 'plugin_command')
    }
    if (statusFilter) {
      result = result.filter((t) => t.status === statusFilter)
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      result = result.filter(
        (t) =>
          t.title.toLowerCase().includes(q) ||
          t.prompt.toLowerCase().includes(q) ||
          (t.plugin_name && t.plugin_name.toLowerCase().includes(q)) ||
          (t.command_name && t.command_name.toLowerCase().includes(q))
      )
    }
    return result
  }, [tasks, activeTab, statusFilter, searchQuery])

  /* --- 加载状态 --- */

  if (loading) {
    return (
      <div className={styles['loading-container']}>
        <Loader size={24} className={styles['loading-spin']} />
        <span>正在加载定时任务...</span>
      </div>
    )
  }

  /* ---- 渲染 ---- */

  return (
    <div className={styles['page']}>
      {/* 页面头部 */}
      <header className={styles['page-header']}>
        <div className={styles['page-header-left']}>
          <h1 className={styles['page-title']}>定时任务</h1>
          <p className={styles['page-subtitle']}>
            智能化任务调度引擎，支持AI提示词与插件命令两种任务类型
          </p>
        </div>
        <div className={styles['page-header-right']}>
          <button
            className={styles['refresh-btn']}
            onClick={() => void loadData()}
            disabled={loading || submitting}
          >
            <RefreshCw size={15} />
            刷新
          </button>
        </div>
      </header>

      {/* 错误提示 */}
      {loadError && <div className={styles['error-banner']}>{loadError}</div>}
      {actionError && <div className={styles['error-banner']}>{actionError}</div>}

      {/* 统计卡片 */}
      <div className={styles['stats-grid']}>
        <div className={`${styles['stat-card']} ${styles['stat-total']}`}>
          <List size={20} />
          <div>
            <span className={styles['stat-value']}>{stats.total}</span>
            <span className={styles['stat-label']}>任务总数</span>
          </div>
        </div>
        <div className={`${styles['stat-card']} ${styles['stat-pending']}`}>
          <Clock size={20} />
          <div>
            <span className={styles['stat-value']}>{stats.pending}</span>
            <span className={styles['stat-label']}>待执行</span>
          </div>
        </div>
        <div className={`${styles['stat-card']} ${styles['stat-running']}`}>
          <Loader size={20} className={styles['stat-spin']} />
          <div>
            <span className={styles['stat-value']}>{stats.running}</span>
            <span className={styles['stat-label']}>执行中</span>
          </div>
        </div>
        <div className={`${styles['stat-card']} ${styles['stat-completed']}`}>
          <CheckCircle size={20} />
          <div>
            <span className={styles['stat-value']}>{stats.completed}</span>
            <span className={styles['stat-label']}>已完成</span>
          </div>
        </div>
        <div className={`${styles['stat-card']} ${styles['stat-failed']}`}>
          <XCircle size={20} />
          <div>
            <span className={styles['stat-value']}>{stats.failed}</span>
            <span className={styles['stat-label']}>失败</span>
          </div>
        </div>
      </div>

      {/* 主标签切换 */}
      <div className={styles['tab-bar']}>
        <button
          type="button"
          className={`${styles['tab']} ${activeTab === 'ai' ? styles['tab-active'] : ''}`}
          onClick={() => setActiveTab('ai')}
        >
          <Brain size={16} />
          AI智能任务
        </button>
        <button
          type="button"
          className={`${styles['tab']} ${activeTab === 'plugin' ? styles['tab-active'] : ''}`}
          onClick={() => setActiveTab('plugin')}
        >
          <Puzzle size={16} />
          插件命令任务
        </button>

        <div className={styles['tab-right']}>
          {/* 搜索 & 过滤 */}
          <div className={styles['search-wrap']}>
            <Search size={14} />
            <input
              type="text"
              placeholder="搜索任务..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className={styles['filter-select']}
          >
            <option value="">全部状态</option>
            <option value="pending">待执行</option>
            <option value="running">执行中</option>
            <option value="completed">已完成</option>
            <option value="failed">失败</option>
            <option value="cancelled">已取消</option>
          </select>
          <button
            type="button"
            className={`${styles['view-btn']} ${viewMode === 'list' ? styles['view-btn-active'] : ''}`}
            onClick={() => setViewMode('list')}
          >
            <List size={14} />
          </button>
          <button
            type="button"
            className={`${styles['view-btn']} ${viewMode === 'grid' ? styles['view-btn-active'] : ''}`}
            onClick={() => setViewMode('grid')}
          >
            <LayoutGrid size={14} />
          </button>
          {selectedTasks.size > 0 && (
            <button
              type="button"
              className={styles['batch-cancel-btn']}
              onClick={() => void handleBatchCancel()}
            >
              <Trash2 size={14} />
              批量取消 ({selectedTasks.size})
            </button>
          )}
        </div>
      </div>

      {/* 内容区域 */}
      <div className={styles['content']}>
        {activeTab === 'ai' ? (
          /* ============ AI智能任务 ============ */
          <div className={styles['ai-layout']}>
            {/* 创建/编辑表单 */}
            <div className={styles['card']}>
              <div className={styles['card-header']}>
                <h2>{editingTaskId !== null ? '编辑AI任务' : '创建AI任务'}</h2>
                {editingTaskId !== null && (
                  <button className="btn btn-ghost" onClick={resetAiForm} type="button">
                    取消编辑
                  </button>
                )}
              </div>

              <form className={styles['form']} onSubmit={(event) => void handleAiSubmit(event)}>
                <label className={styles['field']}>
                  <span>任务标题</span>
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="例如：每日新闻摘要"
                    maxLength={200}
                    required
                  />
                </label>

                <label className={styles['field']}>
                  <span>执行时间</span>
                  <input
                    type="datetime-local"
                    value={scheduledAt}
                    onChange={(e) => setScheduledAt(e.target.value)}
                    required
                  />
                </label>

                <label className={styles['field']}>
                  <span>AI提示词</span>
                  <textarea
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="输入需要AI在指定时间执行的提示词..."
                    rows={6}
                    required
                  />
                </label>

                <div className={styles['inline-fields']}>
                  <label className={styles['field']}>
                    <span>Provider</span>
                    <input
                      value={provider}
                      onChange={(e) => setProvider(e.target.value)}
                      placeholder="默认"
                    />
                  </label>
                  <label className={styles['field']}>
                    <span>Model</span>
                    <input
                      value={model}
                      onChange={(e) => setModel(e.target.value)}
                      placeholder="默认"
                    />
                  </label>
                </div>

                <CronExpressionBuilder
                  onChange={(cfg) => {
                    setIsDaily(cfg.is_daily)
                    if (cfg.is_daily) {
                      setDailyTime(cfg.daily_time)
                      setSelectedWeekdays(new Set(cfg.weekdays.split(',').map(Number)))
                    }
                  }}
                  initialIsDaily={isDaily}
                  initialWeekdays={Array.from(selectedWeekdays).sort().join(',')}
                  initialDailyTime={dailyTime}
                />

                <div className={styles['form-actions']}>
                  <button className={styles['submit-btn']} type="submit" disabled={submitting}>
                    {submitting ? (
                      <>
                        <Loader size={14} className={styles['loading-spin']} /> 提交中...
                      </>
                    ) : editingTaskId !== null ? (
                      '保存修改'
                    ) : (
                      '创建任务'
                    )}
                  </button>
                </div>
              </form>
            </div>

            {/* 任务队列 */}
            <div className={styles['card']}>
              <div className={styles['card-header']}>
                <h2>任务队列 ({filteredTasks.length})</h2>
              </div>
              {filteredTasks.length === 0 ? (
                <div className={styles['empty']}>暂无AI智能任务</div>
              ) : (
                <div className={viewMode === 'grid' ? styles['task-grid'] : styles['task-list']}>
                  {filteredTasks.map((task) => (
                    <article
                      key={task.id}
                      className={`${styles['task-card']} ${
                        selectedTasks.has(task.id) ? styles['task-selected'] : ''
                      }`}
                    >
                      <div className={styles['task-top']}>
                        <label className={styles['task-check']}>
                          <input
                            type="checkbox"
                            checked={selectedTasks.has(task.id)}
                            onChange={() => toggleTaskSelection(task.id)}
                          />
                        </label>
                        <div className={styles['task-info']}>
                          <h3>{task.title}</h3>
                          <span className={styles['task-time']}>
                            {formatDateTime(task.scheduled_at)}
                          </span>
                        </div>
                        <span
                          className={`${styles['badge']} ${styles[`badge-${task.status}`] || ''}`}
                        >
                          {formatStatusLabel(task.status)}
                        </span>
                      </div>

                      <p className={styles['task-prompt']}>{task.prompt}</p>

                      <div className={styles['task-meta']}>
                        <span>Provider: {task.provider || '默认'}</span>
                        <span>Model: {task.model || '默认'}</span>
                        {task.is_daily && task.cron_expression && (
                          <span className={styles['meta-cron']}>
                            {task.cron_expression}
                          </span>
                        )}
                      </div>

                      {task.next_execution_at && (
                        <div className={styles['task-next']}>
                          下次执行: {formatDateTime(task.next_execution_at)}
                        </div>
                      )}

                      {task.last_error_message && (
                        <div className={styles['task-error']}>
                          {task.last_error_message}
                        </div>
                      )}

                      {task.status === 'pending' && (
                        <div className={styles['task-actions']}>
                          <button
                            className={styles['action-btn']}
                            onClick={() => handleEdit(task)}
                            type="button"
                          >
                            编辑
                          </button>
                          <button
                            className={styles['action-btn-danger']}
                            onClick={() => void handleCancelTask(task.id)}
                            disabled={pendingTaskId === task.id}
                            type="button"
                          >
                            {pendingTaskId === task.id ? '取消中...' : '取消'}
                          </button>
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          /* ============ 插件命令任务 ============ */
          <div className={styles['plugin-layout']}>
            {/* 左侧：命令选择 + 参数配置 */}
            <div className={styles['plugin-left']}>
              <div className={styles['card']}>
                <div className={styles['card-header']}>
                  <h2>选择插件命令</h2>
                </div>
                <PluginCommandSelector
                  onSelect={setSelectedCommand}
                  selectedPluginName={selectedCommand?.plugin_name}
                  selectedCommandName={selectedCommand?.command_name}
                />
              </div>

              {selectedCommand && (
                <div className={styles['card']}>
                  <div className={styles['card-header']}>
                    <h2>命令参数</h2>
                    <span className={styles['card-badge']}>
                      {selectedCommand.plugin_name}/{selectedCommand.command_name}
                    </span>
                  </div>
                  <TaskParameterPanel
                    parameters={selectedCommand.parameters}
                    onChange={setCommandParams}
                    initialValues={commandParams}
                  />
                </div>
              )}

              {/* 任务模板 */}
              <TaskTemplateManager
                currentConfig={{
                  task_type: 'plugin_command',
                  title: pluginTaskTitle,
                  plugin_name: selectedCommand?.plugin_name,
                  command_name: selectedCommand?.command_name,
                  command_params: commandParams,
                  is_daily: pluginIsDaily,
                }}
                onLoad={handleTemplateLoad}
              />
            </div>

            {/* 右侧：任务配置 */}
            <div className={styles['plugin-right']}>
              <div className={styles['card']}>
                <div className={styles['card-header']}>
                  <h2>任务配置</h2>
                </div>

                <div className={styles['form']}>
                  <label className={styles['field']}>
                    <span>任务标题</span>
                    <input
                      value={pluginTaskTitle}
                      onChange={(e) => setPluginTaskTitle(e.target.value)}
                      placeholder={
                        selectedCommand
                          ? `执行 ${selectedCommand.plugin_name} - ${selectedCommand.command_name}`
                          : '请先选择插件命令'
                      }
                      maxLength={200}
                    />
                  </label>

                  <label className={styles['field']}>
                    <span>执行时间</span>
                    <input
                      type="datetime-local"
                      value={pluginScheduledAt}
                      onChange={(e) => setPluginScheduledAt(e.target.value)}
                    />
                  </label>

                  <CronExpressionBuilder
                    onChange={(cfg) => {
                      setPluginIsDaily(cfg.is_daily)
                      setPluginCronExpr(cfg.cron_expression)
                      setPluginWeekdays(cfg.weekdays)
                      setPluginDailyTime(cfg.daily_time)
                    }}
                    initialIsDaily={pluginIsDaily}
                    initialWeekdays={pluginWeekdays}
                    initialDailyTime={pluginDailyTime}
                  />

                  {selectedCommand && (
                    <div className={styles['summary']}>
                      <h4>任务摘要</h4>
                      <p>
                        <strong>插件:</strong> {selectedCommand.plugin_name} v
                        {selectedCommand.plugin_version}
                      </p>
                      <p>
                        <strong>命令:</strong> {selectedCommand.command_name}
                      </p>
                      {selectedCommand.command_description && (
                        <p>
                          <strong>说明:</strong> {selectedCommand.command_description}
                        </p>
                      )}
                      <p>
                        <strong>参数:</strong>{' '}
                        {Object.keys(commandParams).length > 0
                          ? Object.entries(commandParams)
                              .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
                              .join(', ')
                          : '无'}
                      </p>
                      <p>
                        <strong>执行方式:</strong>{' '}
                        {pluginIsDaily
                          ? `重复执行 (${pluginCronExpr || '未配置'})`
                          : `单次执行 (${formatDateTime(pluginScheduledAt)})`}
                      </p>
                    </div>
                  )}

                  <div className={styles['form-actions']}>
                    <button
                      className={styles['submit-btn']}
                      type="button"
                      onClick={() => void handlePluginSubmit()}
                      disabled={submitting || !selectedCommand || !pluginTaskTitle.trim()}
                    >
                      {submitting ? (
                        <>
                          <Loader size={14} className={styles['loading-spin']} /> 提交中...
                        </>
                      ) : (
                        '创建插件命令任务'
                      )}
                    </button>
                  </div>
                </div>
              </div>

              {/* 插件任务队列 */}
              <div className={styles['card']}>
                <div className={styles['card-header']}>
                  <h2>插件任务队列 ({filteredTasks.length})</h2>
                </div>
                {filteredTasks.length === 0 ? (
                  <div className={styles['empty']}>暂无插件命令任务</div>
                ) : (
                  <div className={styles['task-list']}>
                    {filteredTasks.map((task) => (
                      <article
                        key={task.id}
                        className={`${styles['task-card']} ${
                          selectedTasks.has(task.id) ? styles['task-selected'] : ''
                        }`}
                      >
                        <div className={styles['task-top']}>
                          <label className={styles['task-check']}>
                            <input
                              type="checkbox"
                              checked={selectedTasks.has(task.id)}
                              onChange={() => toggleTaskSelection(task.id)}
                            />
                          </label>
                          <div className={styles['task-info']}>
                            <h3>{task.title}</h3>
                            <span className={styles['task-time']}>
                              {formatDateTime(task.scheduled_at)}
                            </span>
                          </div>
                          <span
                            className={`${styles['badge']} ${styles[`badge-${task.status}`] || ''}`}
                          >
                            {formatStatusLabel(task.status)}
                          </span>
                        </div>

                        <div className={styles['task-meta']}>
                          {task.plugin_name && (
                            <span className={styles['meta-plugin']}>
                              插件: {task.plugin_name}
                            </span>
                          )}
                          {task.command_name && (
                            <span className={styles['meta-command']}>
                              命令: {task.command_name}
                            </span>
                          )}
                          {task.is_daily && task.cron_expression && (
                            <span className={styles['meta-cron']}>
                              {task.cron_expression}
                            </span>
                          )}
                        </div>

                        {task.next_execution_at && (
                          <div className={styles['task-next']}>
                            下次执行: {formatDateTime(task.next_execution_at)}
                          </div>
                        )}

                        {task.last_error_message && (
                          <div className={styles['task-error']}>
                            {task.last_error_message}
                          </div>
                        )}

                        {task.status === 'pending' && (
                          <div className={styles['task-actions']}>
                            <button
                              className={styles['action-btn']}
                              onClick={() => handleEdit(task)}
                              type="button"
                            >
                              编辑
                            </button>
                            <button
                              className={styles['action-btn-danger']}
                              onClick={() => void handleCancelTask(task.id)}
                              disabled={pendingTaskId === task.id}
                              type="button"
                            >
                              {pendingTaskId === task.id ? '取消中...' : '取消'}
                            </button>
                          </div>
                        )}
                      </article>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* 执行历史 */}
      <TaskLogViewer />
    </div>
  )
}
