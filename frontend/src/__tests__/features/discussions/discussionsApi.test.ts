/**
 * discussionsApi 模块单元测试。
 *
 * 测试目标：
 *   - createDiscussion 正确调用 POST /discussions 并返回 discussion_id
 *   - listDiscussions 正确拼接查询参数并返回分页响应
 *   - getDiscussionDetail 正确调用 GET /discussions/{id}
 *   - reviseDiscussion 正确调用 POST /discussions/{id}/revise
 *   - forceExecuteDiscussion 正确调用 POST /discussions/{id}/force-execute
 *   - groupVotesByRound 按轮次分组并按角色顺序排序
 *   - 异常路径：422 校验失败、401 未授权、404 不存在
 *
 * Mock 策略：mock @/shared/api/api 的 default 导出（axios 实例），
 * 不发起真实网络请求。
 */
import '@testing-library/jest-dom/vitest'
import { beforeEach, describe, it, expect, vi } from 'vitest'
import type { AxiosResponse } from 'axios'

// 提升的 mock 句柄，避免 hoisting 顺序问题
const apiMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('@/shared/api/api', () => ({
  default: {
    get: apiMocks.get,
    post: apiMocks.post,
  },
}))

import {
  createDiscussion,
  listDiscussions,
  getDiscussionDetail,
  reviseDiscussion,
  forceExecuteDiscussion,
  groupVotesByRound,
  type DiscussionCreateRequest,
  type DiscussionReviseRequest,
  type DiscussionForceExecuteRequest,
  type VoteDetail,
} from '@/shared/api/discussionsApi'

describe('discussionsApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('createDiscussion', () => {
    const validRequest: DiscussionCreateRequest = {
      title: '测试任务',
      description: '测试描述',
      proposed_action: {
        type: 'plugin_command',
        payload: { command: 'echo hello' },
      },
      max_rounds: 3,
    }

    it('calls POST /discussions with correct payload', async () => {
      apiMocks.post.mockResolvedValueOnce({
        data: { discussion_id: 'task-1', status: 'created' },
      } as AxiosResponse)

      await createDiscussion(validRequest)

      expect(apiMocks.post).toHaveBeenCalledWith('/discussions', validRequest)
    })

    it('returns discussion_id on success', async () => {
      apiMocks.post.mockResolvedValueOnce({
        data: { discussion_id: 'abc-123', status: 'created' },
      } as AxiosResponse)

      const result = await createDiscussion(validRequest)

      expect(result).toEqual({
        discussion_id: 'abc-123',
        status: 'created',
      })
    })

    it('throws on 422 validation error', async () => {
      const error: Error & { response?: { status: number; data: unknown } } = new Error(
        'Request failed with status code 422'
      )
      error.response = { status: 422, data: { detail: 'Validation error' } }
      apiMocks.post.mockRejectedValueOnce(error)

      await expect(createDiscussion(validRequest)).rejects.toMatchObject({
        response: { status: 422 },
      })
    })

    it('throws on 401 unauthorized', async () => {
      const error: Error & { response?: { status: number; data: unknown } } = new Error(
        'Request failed with status code 401'
      )
      error.response = { status: 401, data: { detail: 'Not authenticated' } }
      apiMocks.post.mockRejectedValueOnce(error)

      await expect(createDiscussion(validRequest)).rejects.toMatchObject({
        response: { status: 401 },
      })
    })
  })

  describe('listDiscussions', () => {
    it('calls GET /discussions with query params', async () => {
      apiMocks.get.mockResolvedValueOnce({
        data: { items: [], total: 0, page: 2, page_size: 10 },
      } as AxiosResponse)

      await listDiscussions({ status: 'discussing', page: 2, page_size: 10 })

      expect(apiMocks.get).toHaveBeenCalledWith('/discussions', {
        params: {
          status: 'discussing',
          page: 2,
          page_size: 10,
        },
      })
    })

    it('uses default page and page_size when not provided', async () => {
      apiMocks.get.mockResolvedValueOnce({
        data: { items: [], total: 0, page: 1, page_size: 20 },
      } as AxiosResponse)

      await listDiscussions()

      expect(apiMocks.get).toHaveBeenCalledWith('/discussions', {
        params: {
          status: undefined,
          page: 1,
          page_size: 20,
        },
      })
    })

    it('returns paginated response', async () => {
      const items = [
        {
          id: 't1',
          title: 'Task 1',
          status: 'discussing',
          round: 1,
          max_rounds: 3,
          created_at: '2026-01-01T00:00:00Z',
          vote_summary: {},
        },
      ]
      apiMocks.get.mockResolvedValueOnce({
        data: { items, total: 25, page: 2, page_size: 10 },
      } as AxiosResponse)

      const result = await listDiscussions({ page: 2, page_size: 10 })

      expect(result.total).toBe(25)
      expect(result.page).toBe(2)
      expect(result.items).toHaveLength(1)
      expect(result.items[0].id).toBe('t1')
    })

    it('handles empty list', async () => {
      apiMocks.get.mockResolvedValueOnce({
        data: { items: [], total: 0, page: 1, page_size: 20 },
      } as AxiosResponse)

      const result = await listDiscussions()

      expect(result.items).toEqual([])
      expect(result.total).toBe(0)
    })
  })

  describe('getDiscussionDetail', () => {
    it('calls GET /discussions/{id}', async () => {
      apiMocks.get.mockResolvedValueOnce({
        data: {
          id: 'task-123',
          title: 'Test',
          status: 'discussing',
          round: 1,
          max_rounds: 3,
          created_at: null,
          vote_summary: {},
          description: '',
          proposed_action: { type: 'plugin_command', payload: {} },
          context: {},
          completed_at: null,
          votes: [],
        },
      } as AxiosResponse)

      await getDiscussionDetail('task-123')

      expect(apiMocks.get).toHaveBeenCalledWith('/discussions/task-123')
    })

    it('returns full task detail with votes grouped by round', async () => {
      const detail = {
        id: 'task-123',
        title: 'Test Task',
        status: 'discussing',
        round: 2,
        max_rounds: 3,
        created_at: '2026-01-01T00:00:00Z',
        vote_summary: {},
        description: 'A test task',
        proposed_action: { type: 'plugin_command', payload: { command: 'ls' } },
        context: {},
        completed_at: null,
        votes: [
          { id: 'v1', role: 'critic', round: 1, vote: 'approve', reason: 'ok', transcript: [], created_at: null },
          { id: 'v2', role: 'validator', round: 1, vote: 'approve', reason: 'ok', transcript: [], created_at: null },
          { id: 'v3', role: 'approver', round: 2, vote: 'approve', reason: 'ok', transcript: [], created_at: null },
        ],
      }
      apiMocks.get.mockResolvedValueOnce({ data: detail } as AxiosResponse)

      const result = await getDiscussionDetail('task-123')

      expect(result.id).toBe('task-123')
      expect(result.votes).toHaveLength(3)
      expect(result.proposed_action.type).toBe('plugin_command')
    })

    it('throws on 404', async () => {
      const error: Error & { response?: { status: number; data: unknown } } = new Error(
        'Request failed with status code 404'
      )
      error.response = { status: 404, data: { detail: 'Not found' } }
      apiMocks.get.mockRejectedValueOnce(error)

      await expect(getDiscussionDetail('nonexistent')).rejects.toMatchObject({
        response: { status: 404 },
      })
    })
  })

  describe('reviseDiscussion', () => {
    it('calls POST /discussions/{id}/revise', async () => {
      apiMocks.post.mockResolvedValueOnce({
        data: {
          id: 'task-1',
          title: 'Test',
          status: 'discussing',
          round: 2,
          max_rounds: 3,
          created_at: null,
          vote_summary: {},
          description: '',
          proposed_action: { type: 'plugin_command', payload: {} },
          context: {},
          completed_at: null,
          votes: [],
          discussion_id: 'task-1',
        },
      } as AxiosResponse)

      const req: DiscussionReviseRequest = {
        proposed_action: { type: 'plugin_command', payload: { command: 'new' } },
        reason: 'Need revision',
      }
      await reviseDiscussion('task-1', req)

      expect(apiMocks.post).toHaveBeenCalledWith('/discussions/task-1/revise', req)
    })

    it('returns new round number', async () => {
      apiMocks.post.mockResolvedValueOnce({
        data: {
          id: 'task-1',
          title: 'Test',
          status: 'discussing',
          round: 2,
          max_rounds: 3,
          created_at: null,
          vote_summary: {},
          description: '',
          proposed_action: { type: 'plugin_command', payload: {} },
          context: {},
          completed_at: null,
          votes: [],
          discussion_id: 'task-1',
        },
      } as AxiosResponse)

      const result = await reviseDiscussion('task-1', {
        proposed_action: { type: 'plugin_command', payload: {} },
        reason: 'reason',
      })

      expect(result.round).toBe(2)
      expect(result.status).toBe('discussing')
    })
  })

  describe('forceExecuteDiscussion', () => {
    it('calls POST /discussions/{id}/force-execute', async () => {
      apiMocks.post.mockResolvedValueOnce({
        data: { discussion_id: 'task-1', status: 'executing' },
      } as AxiosResponse)

      const req: DiscussionForceExecuteRequest = { reason: 'urgent' }
      await forceExecuteDiscussion('task-1', req)

      expect(apiMocks.post).toHaveBeenCalledWith('/discussions/task-1/force-execute', req)
    })

    it('returns executing status', async () => {
      apiMocks.post.mockResolvedValueOnce({
        data: { discussion_id: 'task-1', status: 'executing', bypassed_by: 'admin' },
      } as AxiosResponse)

      const result = await forceExecuteDiscussion('task-1', { reason: 'urgent' })

      expect(result.status).toBe('executing')
      expect(result.discussion_id).toBe('task-1')
    })
  })

  describe('groupVotesByRound', () => {
    it('groups flat vote list by round and sorts by role order', () => {
      const votes: VoteDetail[] = [
        { id: 'v1', role: 'approver', round: 1, vote: 'approve', reason: null, transcript: [], created_at: null },
        { id: 'v2', role: 'critic', round: 1, vote: 'reject', reason: 'no', transcript: [], created_at: null },
        { id: 'v3', role: 'validator', round: 1, vote: 'approve', reason: null, transcript: [], created_at: null },
        { id: 'v4', role: 'critic', round: 2, vote: 'approve', reason: null, transcript: [], created_at: null },
      ]

      const groups = groupVotesByRound(votes)

      expect(groups).toHaveLength(2)
      expect(groups[0].round).toBe(1)
      expect(groups[0].votes).toHaveLength(3)
      // 角色顺序：critic -> validator -> approver
      expect(groups[0].votes[0].role).toBe('critic')
      expect(groups[0].votes[1].role).toBe('validator')
      expect(groups[0].votes[2].role).toBe('approver')
      expect(groups[1].round).toBe(2)
      expect(groups[1].votes).toHaveLength(1)
    })

    it('returns empty array for empty input', () => {
      expect(groupVotesByRound([])).toEqual([])
    })

    it('sorts rounds in ascending order', () => {
      const votes: VoteDetail[] = [
        { id: 'v1', role: 'critic', round: 3, vote: 'approve', reason: null, transcript: [], created_at: null },
        { id: 'v2', role: 'critic', round: 1, vote: 'approve', reason: null, transcript: [], created_at: null },
        { id: 'v3', role: 'critic', round: 2, vote: 'approve', reason: null, transcript: [], created_at: null },
      ]

      const groups = groupVotesByRound(votes)

      expect(groups.map((g) => g.round)).toEqual([1, 2, 3])
    })
  })
})
