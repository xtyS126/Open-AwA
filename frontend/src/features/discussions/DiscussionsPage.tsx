/**
 * DiscussionsPage 讨论任务主页面。
 *
 * 布局：左侧任务列表（200-280px 宽）+ 右侧详情面板。
 * 顶部工具栏：标题、新建按钮、刷新按钮、状态过滤器。
 *
 * 响应式：小屏幕（< 768px）时改为单列堆叠，列表与详情面板上下排列。
 *
 * [PERF] 使用精确选择器订阅 store 字段，避免整个 store 变化触发重渲染。
 * 列表使用 useMemo 缓存排序结果。
 */
import React, { useEffect, useMemo, useCallback } from 'react'
import { useNavigate, useParams } from '@/shared/routing'
import { Plus, RefreshCw, MessagesSquare } from 'lucide-react'
import { EmptyState, Button } from '@/shared/components/ui'
import { useI18nStore } from '@/i18n'
import { appLogger } from '@/shared/utils/logger'
import { useDiscussionStore, type DiscussionStatusFilter } from './store/discussionStore'
import DiscussionTaskItem from './components/DiscussionTaskItem'
import DiscussionDetailPanel from './components/DiscussionDetailPanel'
import CreateDiscussionModal from './components/CreateDiscussionModal'
import styles from './DiscussionsPage.module.css'

/** 过滤器选项 */
const FILTER_OPTIONS: ReadonlyArray<{ value: DiscussionStatusFilter; labelKey: string }> = [
  { value: 'all', labelKey: 'discussions.filter.all' },
  { value: 'in_progress', labelKey: 'discussions.filter.in_progress' },
  { value: 'completed', labelKey: 'discussions.filter.completed' },
]

const DiscussionsPage: React.FC = () => {
  const t = useI18nStore((s) => s.t)
  const navigate = useNavigate()
  const { id: routeId } = useParams<{ id: string }>()

  // 精确选择器订阅
  const list = useDiscussionStore((s) => s.list)
  const total = useDiscussionStore((s) => s.total)
  const statusFilter = useDiscussionStore((s) => s.statusFilter)
  const selectedTask = useDiscussionStore((s) => s.selectedTask)
  const isLoadingList = useDiscussionStore((s) => s.isLoadingList)
  const isLoadingDetail = useDiscussionStore((s) => s.isLoadingDetail)
  const error = useDiscussionStore((s) => s.error)
  const isCreateModalOpen = useDiscussionStore((s) => s.isCreateModalOpen)
  const fetchList = useDiscussionStore((s) => s.fetchList)
  const selectTask = useDiscussionStore((s) => s.selectTask)
  const setStatusFilter = useDiscussionStore((s) => s.setStatusFilter)
  const setCreateModalOpen = useDiscussionStore((s) => s.setCreateModalOpen)
  const clearError = useDiscussionStore((s) => s.clearError)

  // 初始加载列表
  useEffect(() => {
    void fetchList({ page: 1 })
  }, [fetchList])

  // 路由参数变化时自动选中任务
  useEffect(() => {
    if (routeId) {
      void selectTask(routeId)
    }
  }, [routeId, selectTask])

  /** 处理任务点击：选中任务并更新 URL */
  const handleSelectTask = useCallback(
    (taskId: string) => {
      // 清空错误状态，避免旧错误持续显示
      clearError()
      void selectTask(taskId)
      // 更新 URL 但不触发导航（保留查询参数）
      navigate(`/discussions/${taskId}`, { replace: true })
    },
    [selectTask, navigate, clearError]
  )

  /** 处理刷新 */
  const handleRefresh = useCallback(() => {
    void fetchList()
    if (selectedTask) {
      void selectTask(selectedTask.id)
    }
  }, [fetchList, selectTask, selectedTask])

  /** 处理新建按钮 */
  const handleCreateClick = useCallback(() => {
    setCreateModalOpen(true)
  }, [setCreateModalOpen])

  /** 关闭新建 modal */
  const handleCloseCreateModal = useCallback(() => {
    setCreateModalOpen(false)
  }, [setCreateModalOpen])

  /** 处理过滤器切换 */
  const handleFilterChange = useCallback(
    (filter: DiscussionStatusFilter) => {
      setStatusFilter(filter)
    },
    [setStatusFilter]
  )

  // 列表数据已由 store 过滤，此处仅做稳定性排序（按 created_at 倒序）
  const sortedList = useMemo(() => {
    return [...list].sort((a, b) => {
      const timeA = a.created_at ? new Date(a.created_at).getTime() : 0
      const timeB = b.created_at ? new Date(b.created_at).getTime() : 0
      return timeB - timeA
    })
  }, [list])

  // 错误提示：使用 Toast 风格的临时提示
  // 错误信息存储在 store.error 中，组件层渲染为顶部 banner
  useEffect(() => {
    if (error) {
      appLogger.warning({
        event: 'discussion_page_error_visible',
        module: 'discussions',
        action: 'render',
        status: 'warning',
        message: '页面错误已显示',
        extra: { error },
      })
    }
  }, [error])

  return (
    <div className={styles.page}>
      {/* 顶部工具栏 */}
      <header className={styles.toolbar}>
        <div className={styles.titleArea}>
          <MessagesSquare size={20} aria-hidden="true" />
          <div>
            <h1 className={styles.title}>{t('discussions.title')}</h1>
            <p className={styles.subtitle}>{t('discussions.subtitle')}</p>
          </div>
        </div>

        <div className={styles.actions}>
          {/* 状态过滤器 */}
          <div className={styles.filterGroup} role="tablist" aria-label={t('app.status')}>
            {FILTER_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`${styles.filterBtn} ${
                  statusFilter === option.value ? styles.filterBtnActive : ''
                }`}
                onClick={() => handleFilterChange(option.value)}
                role="tab"
                aria-selected={statusFilter === option.value}
                aria-label={t(option.labelKey)}
              >
                {t(option.labelKey)}
              </button>
            ))}
          </div>

          {/* 刷新按钮 */}
          <Button
            variant="secondary"
            size="sm"
            onClick={handleRefresh}
            disabled={isLoadingList}
            aria-label={t('discussions.refresh')}
          >
            <RefreshCw size={14} className={isLoadingList ? styles.spinning : ''} />
            {t('discussions.refresh')}
          </Button>

          {/* 新建按钮 */}
          <Button
            variant="primary"
            size="sm"
            onClick={handleCreateClick}
            aria-label={t('discussions.create')}
          >
            <Plus size={14} />
            {t('discussions.create')}
          </Button>
        </div>
      </header>

      {/* 错误提示 banner */}
      {error && (
        <div className={styles.errorBanner} role="alert">
          {error}
          <button
            type="button"
            className={styles.errorClose}
            onClick={clearError}
            aria-label={t('app.close')}
          >
            ×
          </button>
        </div>
      )}

      {/* 主体：列表 + 详情 */}
      <div className={styles.body}>
        {/* 左侧：任务列表 */}
        <aside className={styles.listPane} aria-label={t('discussions.title')}>
          <div className={styles.listHeader}>
            <span className={styles.listCount}>
              {t('app.totalCount', { count: String(total) })}
            </span>
          </div>

          <div className={styles.list}>
            {isLoadingList && list.length === 0 ? (
              <div className={styles.loadingPlaceholder} aria-busy="true">
                {t('app.loading')}
              </div>
            ) : sortedList.length === 0 ? (
              <EmptyState
                icon={<MessagesSquare size={36} />}
                title={t('discussions.empty.no_tasks')}
                actionLabel={t('discussions.create')}
                onAction={handleCreateClick}
              />
            ) : (
              sortedList.map((task) => (
                <DiscussionTaskItem
                  key={task.id}
                  task={task}
                  isSelected={selectedTask?.id === task.id}
                  onClick={handleSelectTask}
                />
              ))
            )}
          </div>
        </aside>

        {/* 右侧：详情面板 */}
        <main className={styles.detailPane}>
          <DiscussionDetailPanel
            task={selectedTask}
            isLoading={isLoadingDetail}
          />
        </main>
      </div>

      {/* 新建讨论 modal */}
      <CreateDiscussionModal open={isCreateModalOpen} onClose={handleCloseCreateModal} />
    </div>
  )
}

export default DiscussionsPage
