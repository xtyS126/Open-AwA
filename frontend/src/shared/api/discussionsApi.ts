/**
 * 讨论任务 API 模块。
 *
 * 封装多 Agent 讨论任务工作流的所有 REST 调用，
 * 类型与 backend/api/routes/discussions.py 中的 Pydantic 响应模型保持一致。
 *
 * 端点列表（路由前缀 /api/discussions）：
 *   - POST /                    创建讨论任务
 *   - GET /                     分页查询任务列表
 *   - GET /{id}                 查询任务详情
 *   - POST /{id}/revise         提交修订
 *   - POST /{id}/force-execute  紧急旁路执行（admin）
 *
 * 注意：SSE 端点 GET /{id}/stream 不在此封装，
 * 由 DiscussionStream 组件直接使用 EventSource 订阅，
 * 以保持长连接的生命周期可控（Cookie 鉴权，不通过 query 传 token）。
 */
import api from '@/shared/api/api'
import type { AxiosResponse } from 'axios'

// ── 枚举类型 ──────────────────────────────────────────────────────

/** 讨论任务状态机 */
export type DiscussionStatus =
  | 'created'
  | 'discussing'
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'executing'
  | 'completed'
  | 'failed'

/** 讨论角色：批判性审查 / 可行性验证 / 终审批准 */
export type DiscussionRole = 'critic' | 'validator' | 'approver'

/** 投票决策：通过 / 拒绝 / 弃权 */
export type VoteDecision = 'approve' | 'reject' | 'abstain'

// ── 数据结构类型 ──────────────────────────────────────────────────

/** 待评审的提议动作，type 标识执行器类型，payload 为执行器特定参数 */
export interface ProposedAction {
  type: string
  payload: Record<string, unknown>
}

/** 单条投票记录详情 */
export interface VoteDetail {
  id: string
  role: DiscussionRole
  round: number
  vote: VoteDecision
  reason: string | null
  transcript: unknown[]
  created_at: string | null
}

/** 各角色最新投票摘要，按角色聚合 */
export interface VoteSummary {
  critic?: VoteDetail | null
  validator?: VoteDetail | null
  approver?: VoteDetail | null
}

/** 讨论任务列表项 */
export interface DiscussionTaskListItem {
  id: string
  title: string
  status: DiscussionStatus
  round: number
  max_rounds: number
  created_at: string | null
  updated_at?: string | null
  vote_summary: VoteSummary
}

/** 讨论任务详情（含完整讨论历史） */
export interface DiscussionTaskDetail extends DiscussionTaskListItem {
  description: string
  proposed_action: ProposedAction
  context: Record<string, unknown>
  completed_at: string | null
  /** 后端返回扁平投票列表，前端按 round 分组展示 */
  votes: VoteDetail[]
}

// ── 请求 / 响应类型 ──────────────────────────────────────────────

/** 创建讨论任务请求 */
export interface DiscussionCreateRequest {
  title: string
  description: string
  proposed_action: ProposedAction
  context?: Record<string, unknown>
  max_rounds?: number
}

/** 创建讨论任务响应 */
export interface DiscussionCreateResponse {
  discussion_id: string
  status: 'created'
}

/** 列表查询参数 */
export interface DiscussionListParams {
  status?: DiscussionStatus
  page?: number
  page_size?: number
}

/** 列表查询响应 */
export interface DiscussionListResponse {
  items: DiscussionTaskListItem[]
  total: number
  page: number
  page_size: number
}

/** 修订请求 */
export interface DiscussionReviseRequest {
  proposed_action: ProposedAction
  reason: string
}

/** 修订响应（后端返回最新任务详情） */
export interface DiscussionReviseResponse extends DiscussionTaskDetail {
  discussion_id: string
  status: DiscussionStatus
  round: number
}

/** 紧急旁路执行请求 */
export interface DiscussionForceExecuteRequest {
  reason: string
}

/** 紧急旁路执行响应 */
export interface DiscussionForceExecuteResponse {
  discussion_id: string
  status: 'executing'
  bypassed_by?: string
  reason?: string
  message?: string
}

// ── API 调用 ──────────────────────────────────────────────────────

const BASE = '/discussions'

/**
 * 创建讨论任务。
 *
 * 后端返回 201 + { discussion_id, status }，自动触发首轮讨论。
 */
export async function createDiscussion(
  req: DiscussionCreateRequest
): Promise<DiscussionCreateResponse> {
  const response: AxiosResponse<DiscussionCreateResponse> = await api.post(BASE, req)
  return response.data
}

/**
 * 分页查询讨论任务列表。
 *
 * 仅返回当前用户创建的任务，按 created_at 倒序。
 */
export async function listDiscussions(
  params: DiscussionListParams = {}
): Promise<DiscussionListResponse> {
  const response: AxiosResponse<DiscussionListResponse> = await api.get(BASE, {
    params: {
      status: params.status,
      page: params.page ?? 1,
      page_size: params.page_size ?? 20,
    },
  })
  return response.data
}

/**
 * 查询单个讨论任务详情（含所有轮次讨论历史）。
 */
export async function getDiscussionDetail(
  id: string
): Promise<DiscussionTaskDetail> {
  const response: AxiosResponse<DiscussionTaskDetail> = await api.get(`${BASE}/${id}`)
  return response.data
}

/**
 * 提交修订后的提议动作，触发新一轮讨论。
 *
 * 后端返回最新任务详情（DiscussionTaskResponse）。
 */
export async function reviseDiscussion(
  id: string,
  req: DiscussionReviseRequest
): Promise<DiscussionReviseResponse> {
  const response: AxiosResponse<DiscussionReviseResponse> = await api.post(
    `${BASE}/${id}/revise`,
    req
  )
  return response.data
}

/**
 * 紧急旁路执行（仅 admin 可调用，跳过未完成投票直接进入执行状态）。
 */
export async function forceExecuteDiscussion(
  id: string,
  req: DiscussionForceExecuteRequest
): Promise<DiscussionForceExecuteResponse> {
  const response: AxiosResponse<DiscussionForceExecuteResponse> = await api.post(
    `${BASE}/${id}/force-execute`,
    req
  )
  return response.data
}

// ── 辅助函数：将扁平投票列表按轮次分组 ─────────────────────────

/** 按轮次分组的投票记录 */
export interface VoteGroup {
  round: number
  votes: VoteDetail[]
}

/**
 * 将扁平投票列表按 round 分组并按角色顺序排序。
 *
 * 角色排序固定为 critic -> validator -> approver，
 * 与后端编排器执行顺序一致，便于前端按时间线展示。
 */
export function groupVotesByRound(votes: VoteDetail[]): VoteGroup[] {
  const roleOrder: Record<DiscussionRole, number> = {
    critic: 0,
    validator: 1,
    approver: 2,
  }
  const groups = new Map<number, VoteDetail[]>()
  for (const vote of votes) {
    const list = groups.get(vote.round) ?? []
    list.push(vote)
    groups.set(vote.round, list)
  }
  return Array.from(groups.entries())
    .map(([round, list]) => ({
      round,
      votes: list.sort((a, b) => {
        const orderA = roleOrder[a.role as DiscussionRole] ?? 99
        const orderB = roleOrder[b.role as DiscussionRole] ?? 99
        return orderA - orderB
      }),
    }))
    .sort((a, b) => a.round - b.round)
}
