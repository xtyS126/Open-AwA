/**
 * 讨论任务 Zustand 状态管理。
 *
 * 管理：列表分页、当前选中任务详情、loading/error 状态、新建 modal 显隐。
 * 所有 API 调用错误统一捕获并写入 error 字段，UI 通过 Toast 展示。
 *
 * 使用 set/get 模式，错误信息提取复用 getErrorMessage 工具函数，
 * 遵守项目规范：禁止吞异常，关键路径错误必须传播到上层 UI。
 */
import { create } from 'zustand'
import { appLogger } from '@/shared/utils/logger'
import { getErrorMessage } from '@/shared/utils/errorMessages'
import {
  createDiscussion,
  forceExecuteDiscussion,
  getDiscussionDetail,
  listDiscussions,
  reviseDiscussion,
  type DiscussionCreateRequest,
  type DiscussionForceExecuteRequest,
  type DiscussionListParams,
  type DiscussionReviseRequest,
  type DiscussionStatus,
  type DiscussionTaskDetail,
  type DiscussionTaskListItem,
} from '@/shared/api/discussionsApi'

/** 进行中状态过滤集合（用于 filter.in_progress） */
const IN_PROGRESS_STATUSES: ReadonlySet<DiscussionStatus> = new Set<DiscussionStatus>([
  'created',
  'discussing',
  'pending_approval',
  'executing',
])

/** 已完成状态过滤集合（用于 filter.completed） */
const COMPLETED_STATUSES: ReadonlySet<DiscussionStatus> = new Set<DiscussionStatus>([
  'approved',
  'rejected',
  'completed',
  'failed',
])

/** 状态过滤器值 */
export type DiscussionStatusFilter = DiscussionStatus | 'all' | 'in_progress' | 'completed'

interface DiscussionState {
  /** 任务列表 */
  list: DiscussionTaskListItem[]
  /** 总数（用于分页） */
  total: number
  /** 当前页码 */
  page: number
  /** 每页数量 */
  pageSize: number
  /** 状态过滤器 */
  statusFilter: DiscussionStatusFilter
  /** 当前选中任务详情 */
  selectedTask: DiscussionTaskDetail | null
  /** 列表加载中 */
  isLoadingList: boolean
  /** 详情加载中 */
  isLoadingDetail: boolean
  /** 提交中（创建/修订/强制执行） */
  isSubmitting: boolean
  /** 错误信息 */
  error: string | null
  /** 新建 modal 显隐 */
  isCreateModalOpen: boolean
}

interface DiscussionActions {
  /** 拉取列表，使用当前 statusFilter 翻译为后端可识别的 status */
  fetchList: (params?: DiscussionListParams) => Promise<void>
  /** 选中任务，传 null 清空 */
  selectTask: (id: string | null) => Promise<void>
  /** 创建任务，返回新任务 id */
  createTask: (req: DiscussionCreateRequest) => Promise<string>
  /** 提交修订 */
  reviseTask: (id: string, req: DiscussionReviseRequest) => Promise<void>
  /** 紧急旁路执行 */
  forceExecute: (id: string, req: DiscussionForceExecuteRequest) => Promise<void>
  /** 打开/关闭新建 modal */
  setCreateModalOpen: (open: boolean) => void
  /** 设置状态过滤器 */
  setStatusFilter: (status: DiscussionStatusFilter) => void
  /** 清空错误 */
  clearError: () => void
}

type DiscussionStore = DiscussionState & DiscussionActions

/**
 * 将前端过滤器值转换为后端 status 参数。
 *
 * 后端仅接受单个 status 字符串，前端聚合过滤器（in_progress/completed）
 * 需在前端过滤；后端只接收具体状态或全量（不传 status）。
 */
function resolveBackendStatus(filter: DiscussionStatusFilter): DiscussionStatus | undefined {
  if (filter === 'all' || filter === 'in_progress' || filter === 'completed') {
    return undefined
  }
  return filter
}

/**
 * 在前端按聚合过滤器筛选列表。
 *
 * 后端不支持 in_progress / completed 复合 status 查询，
 * 此处在 fetchList 拉到全量后于前端过滤。
 */
function filterListByStatus(
  items: DiscussionTaskListItem[],
  filter: DiscussionStatusFilter
): DiscussionTaskListItem[] {
  if (filter === 'all') return items
  if (filter === 'in_progress') {
    return items.filter((item) => IN_PROGRESS_STATUSES.has(item.status))
  }
  if (filter === 'completed') {
    return items.filter((item) => COMPLETED_STATUSES.has(item.status))
  }
  return items
}

export const useDiscussionStore = create<DiscussionStore>((set, get) => ({
  list: [],
  total: 0,
  page: 1,
  pageSize: 20,
  statusFilter: 'all',
  selectedTask: null,
  isLoadingList: false,
  isLoadingDetail: false,
  isSubmitting: false,
  error: null,
  isCreateModalOpen: false,

  fetchList: async (params) => {
    const { statusFilter, page, pageSize } = get()
    set({ isLoadingList: true, error: null })
    try {
      const response = await listDiscussions({
        status: resolveBackendStatus(statusFilter),
        page: params?.page ?? page,
        page_size: params?.page_size ?? pageSize,
      })
      const filteredItems = filterListByStatus(response.items, statusFilter)
      set({
        list: filteredItems,
        total: response.total,
        page: response.page,
        pageSize: response.page_size,
        isLoadingList: false,
      })
    } catch (error) {
      const message = getErrorMessage(error, '加载讨论列表失败')
      appLogger.error({
        event: 'discussion_fetch_list_failed',
        module: 'discussions',
        action: 'fetch_list',
        status: 'failure',
        message,
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      set({ isLoadingList: false, error: message })
    }
  },

  selectTask: async (id) => {
    if (id === null) {
      set({ selectedTask: null })
      return
    }
    set({ isLoadingDetail: true, error: null })
    try {
      const detail = await getDiscussionDetail(id)
      set({ selectedTask: detail, isLoadingDetail: false })
    } catch (error) {
      const message = getErrorMessage(error, '加载讨论详情失败')
      appLogger.error({
        event: 'discussion_select_task_failed',
        module: 'discussions',
        action: 'select_task',
        status: 'failure',
        message,
        extra: {
          discussion_id: id,
          error: error instanceof Error ? error.message : String(error),
        },
      })
      set({ isLoadingDetail: false, error: message })
    }
  },

  createTask: async (req) => {
    set({ isSubmitting: true, error: null })
    try {
      const response = await createDiscussion(req)
      appLogger.info({
        event: 'discussion_create_success',
        module: 'discussions',
        action: 'create',
        status: 'success',
        message: '讨论任务创建成功',
        extra: { discussion_id: response.discussion_id },
      })
      // 创建后刷新列表
      await get().fetchList()
      set({ isSubmitting: false, isCreateModalOpen: false })
      return response.discussion_id
    } catch (error) {
      const message = getErrorMessage(error, '创建讨论失败')
      appLogger.error({
        event: 'discussion_create_failed',
        module: 'discussions',
        action: 'create',
        status: 'failure',
        message,
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      set({ isSubmitting: false, error: message })
      throw error
    }
  },

  reviseTask: async (id, req) => {
    set({ isSubmitting: true, error: null })
    try {
      const updated = await reviseDiscussion(id, req)
      appLogger.info({
        event: 'discussion_revise_success',
        module: 'discussions',
        action: 'revise',
        status: 'success',
        message: '讨论任务修订成功',
        extra: { discussion_id: id, round: updated.round },
      })
      // 修订成功后刷新详情与列表
      await get().selectTask(id)
      await get().fetchList()
      set({ isSubmitting: false })
    } catch (error) {
      const message = getErrorMessage(error, '修订讨论失败')
      appLogger.error({
        event: 'discussion_revise_failed',
        module: 'discussions',
        action: 'revise',
        status: 'failure',
        message,
        extra: {
          discussion_id: id,
          error: error instanceof Error ? error.message : String(error),
        },
      })
      set({ isSubmitting: false, error: message })
      throw error
    }
  },

  forceExecute: async (id, req) => {
    set({ isSubmitting: true, error: null })
    try {
      await forceExecuteDiscussion(id, req)
      appLogger.info({
        event: 'discussion_force_execute_success',
        module: 'discussions',
        action: 'force_execute',
        status: 'success',
        message: '讨论任务强制执行已触发',
        extra: { discussion_id: id },
      })
      // 强制执行后刷新详情与列表
      await get().selectTask(id)
      await get().fetchList()
      set({ isSubmitting: false })
    } catch (error) {
      const message = getErrorMessage(error, '强制执行失败')
      appLogger.error({
        event: 'discussion_force_execute_failed',
        module: 'discussions',
        action: 'force_execute',
        status: 'failure',
        message,
        extra: {
          discussion_id: id,
          error: error instanceof Error ? error.message : String(error),
        },
      })
      set({ isSubmitting: false, error: message })
      throw error
    }
  },

  setCreateModalOpen: (open) => set({ isCreateModalOpen: open }),

  setStatusFilter: (status) => {
    set({ statusFilter: status, page: 1 })
    // 切换过滤器后立即重新拉取
    void get().fetchList({ page: 1 })
  },

  clearError: () => set({ error: null }),
}))
