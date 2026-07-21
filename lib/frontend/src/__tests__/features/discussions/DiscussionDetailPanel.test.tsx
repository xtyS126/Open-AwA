/**
 * DiscussionDetailPanel 讨论任务详情面板单元测试。
 *
 * 测试目标：
 *   - 渲染：任务标题、状态徽章、proposed_action 摘要、description、按轮次分组投票
 *   - 操作按钮：discussing/pending_approval 显示修订表单，completed/approved 隐藏
 *   - 强制执行按钮：仅 admin 可见
 *   - 投票状态：待投票/已通过/已拒绝的图标展示
 *   - DiscussionStream 集成：传入正确的 discussionId
 *
 * Mock：
 *   - @/features/discussions/components/DiscussionStream：避免 EventSource 依赖
 *   - @/shared/utils/logger：避免日志副作用
 *   - @/shared/store/authStore：通过 setState 控制用户角色
 *   - @/features/discussions/store/discussionStore：通过 setState 控制 isSubmitting
 */
import '@testing-library/jest-dom/vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest'
import DiscussionDetailPanel from '@/features/discussions/components/DiscussionDetailPanel'
import { useAuthStore } from '@/shared/store/authStore'
import { useDiscussionStore } from '@/features/discussions/store/discussionStore'
import type {
  DiscussionTaskDetail,
  VoteDetail,
  VoteSummary,
} from '@/shared/api/discussionsApi'

// mock DiscussionStream，捕获传入的 discussionId
const discussionStreamMock = vi.fn()
vi.mock('@/features/discussions/components/DiscussionStream', () => ({
  default: (props: unknown) => {
    discussionStreamMock(props)
    const { discussionId } = props as { discussionId: string }
    return <div data-testid="discussion-stream-mock" data-discussion-id={discussionId} />
  },
}))

vi.mock('@/shared/utils/logger', () => ({
  appLogger: {
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}))

/** 构造单条投票记录 */
function createMockVote(
  overrides: Partial<VoteDetail> = {}
): VoteDetail {
  return {
    id: `vote-${Math.random().toString(36).slice(2, 8)}`,
    role: 'critic',
    round: 1,
    vote: 'approve',
    reason: '通过',
    transcript: [],
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

/** 构造任务详情 mock 数据 */
function createMockTaskDetail(
  overrides: Partial<DiscussionTaskDetail> = {}
): DiscussionTaskDetail {
  return {
    id: 'task-1',
    title: '测试任务详情',
    status: 'discussing',
    round: 1,
    max_rounds: 3,
    created_at: '2026-01-01T00:00:00Z',
    vote_summary: {},
    description: '这是一个测试任务描述',
    proposed_action: {
      type: 'plugin_command',
      payload: { command: 'echo', args: ['hello'] },
    },
    context: {},
    completed_at: null,
    votes: [],
    ...overrides,
  }
}

describe('DiscussionDetailPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 重置 authStore 和 discussionStore
    useAuthStore.setState({
      user: { username: 'testuser', role: 'user' },
      apiKey: null,
      isAuthenticated: true,
      isInitialized: true,
    })
    useDiscussionStore.setState({
      isSubmitting: false,
      error: null,
    })
  })

  afterEach(() => {
    cleanup()
  })

  describe('渲染测试', () => {
    it('renders task title and status', () => {
      const task = createMockTaskDetail({
        title: '任务标题XYZ',
        status: 'discussing',
      })

      render(<DiscussionDetailPanel task={task} />)

      expect(screen.getByText('任务标题XYZ')).toBeInTheDocument()
      // 讨论中状态徽章文案
      expect(screen.getByText('讨论中')).toBeInTheDocument()
    })

    it('renders proposed action summary', () => {
      const task = createMockTaskDetail({
        proposed_action: {
          type: 'plugin_command',
          payload: { command: 'echo', args: ['hello'] },
        },
      })

      render(<DiscussionDetailPanel task={task} />)

      // 动作类型显示（<code> 元素中）
      const typeCode = screen.getByText('plugin_command')
      expect(typeCode).toBeInTheDocument()
      // payload 摘要显示（JSON 字符串，可能同时出现在 ReviseForm textarea 中）
      const payloadMatches = screen.getAllByText(/"command"/)
      expect(payloadMatches.length).toBeGreaterThanOrEqual(1)
    })

    it('renders description', () => {
      const task = createMockTaskDetail({
        description: '这是一段详细的任务描述文本',
      })

      render(<DiscussionDetailPanel task={task} />)

      expect(screen.getByText('这是一段详细的任务描述文本')).toBeInTheDocument()
    })

    it('renders votes grouped by round', () => {
      const votes: VoteDetail[] = [
        createMockVote({ id: 'v1', role: 'critic', round: 1, vote: 'approve' }),
        createMockVote({ id: 'v2', role: 'validator', round: 1, vote: 'approve' }),
        createMockVote({ id: 'v3', role: 'approver', round: 1, vote: 'reject' }),
        createMockVote({ id: 'v4', role: 'critic', round: 2, vote: 'approve' }),
      ]
      const task = createMockTaskDetail({
        status: 'completed',
        votes,
        round: 2,
      })

      render(<DiscussionDetailPanel task={task} />)

      // 第 1 轮和第 2 轮标题都应出现
      // 注意：VoteSummaryView 也会渲染「第 N 轮」，故使用 getAllByText
      const round1Matches = screen.getAllByText(/第 1 轮/)
      expect(round1Matches.length).toBeGreaterThanOrEqual(1)
      const round2Matches = screen.getAllByText(/第 2 轮/)
      expect(round2Matches.length).toBeGreaterThanOrEqual(1)
      // 角色文案出现（critic -> 批判性审查员）
      const criticLabels = screen.getAllByText('批判性审查员')
      expect(criticLabels.length).toBeGreaterThanOrEqual(2)
    })
  })

  describe('操作按钮测试', () => {
    it('shows revise form when status is discussing', () => {
      const task = createMockTaskDetail({
        status: 'discussing',
        round: 1,
        max_rounds: 3,
      })

      render(<DiscussionDetailPanel task={task} />)

      // ReviseForm 标题为「修订」
      expect(screen.getByRole('heading', { name: '修订' })).toBeInTheDocument()
    })

    it('shows revise form when status is pending_approval', () => {
      const task = createMockTaskDetail({
        status: 'pending_approval',
        round: 1,
        max_rounds: 3,
      })

      render(<DiscussionDetailPanel task={task} />)

      expect(screen.getByRole('heading', { name: '修订' })).toBeInTheDocument()
    })

    it('hides revise form when status is completed', () => {
      const task = createMockTaskDetail({
        status: 'completed',
        round: 2,
        max_rounds: 3,
      })

      render(<DiscussionDetailPanel task={task} />)

      expect(screen.queryByRole('heading', { name: '修订' })).not.toBeInTheDocument()
    })

    it('hides revise form when status is approved', () => {
      const task = createMockTaskDetail({
        status: 'approved',
        round: 1,
        max_rounds: 3,
      })

      render(<DiscussionDetailPanel task={task} />)

      expect(screen.queryByRole('heading', { name: '修订' })).not.toBeInTheDocument()
    })

    it('shows force execute button only for admin', () => {
      // 普通用户不显示
      useAuthStore.setState({ user: { username: 'normal', role: 'user' } })
      const task = createMockTaskDetail({ status: 'discussing' })

      const { rerender } = render(<DiscussionDetailPanel task={task} />)

      expect(screen.queryByText('强制执行')).not.toBeInTheDocument()

      // admin 显示
      useAuthStore.setState({ user: { username: 'admin', role: 'admin' } })

      rerender(<DiscussionDetailPanel task={task} />)

      expect(screen.getByText('强制执行')).toBeInTheDocument()
    })
  })

  describe('投票状态测试', () => {
    it('renders pending vote icons when no votes', () => {
      const voteSummary: VoteSummary = {
        critic: undefined,
        validator: undefined,
        approver: undefined,
      }
      const task = createMockTaskDetail({
        status: 'completed',
        vote_summary: voteSummary,
        round: 1,
      })

      render(<DiscussionDetailPanel task={task} />)

      // 三个角色都显示「待投票」
      const pendingVotes = screen.getAllByText('待投票')
      expect(pendingVotes).toHaveLength(3)
    })

    it('renders approve icons when all approved', () => {
      const voteSummary: VoteSummary = {
        critic: createMockVote({ role: 'critic', vote: 'approve' }),
        validator: createMockVote({ role: 'validator', vote: 'approve' }),
        approver: createMockVote({ role: 'approver', vote: 'approve' }),
      }
      const task = createMockTaskDetail({
        status: 'completed',
        vote_summary: voteSummary,
        round: 1,
      })

      render(<DiscussionDetailPanel task={task} />)

      // 三个角色都显示「通过」
      const approveVotes = screen.getAllByText('通过')
      expect(approveVotes.length).toBeGreaterThanOrEqual(3)
    })

    it('renders reject icon when one rejected', () => {
      const voteSummary: VoteSummary = {
        critic: createMockVote({ role: 'critic', vote: 'reject', reason: '不通过' }),
        validator: createMockVote({ role: 'validator', vote: 'approve' }),
        approver: createMockVote({ role: 'approver', vote: 'approve' }),
      }
      const task = createMockTaskDetail({
        status: 'completed',
        vote_summary: voteSummary,
        round: 1,
      })

      render(<DiscussionDetailPanel task={task} />)

      // critic 显示「拒绝」
      expect(screen.getByText('拒绝')).toBeInTheDocument()
    })
  })

  describe('DiscussionStream 集成测试', () => {
    it('renders DiscussionStream component', () => {
      const task = createMockTaskDetail({
        status: 'discussing',
        id: 'stream-task-1',
      })

      render(<DiscussionDetailPanel task={task} />)

      // DiscussionStream 仅在 live 状态下渲染
      expect(discussionStreamMock).toHaveBeenCalled()
      expect(screen.getByTestId('discussion-stream-mock')).toBeInTheDocument()
    })

    it('passes correct discussion id to stream', () => {
      const task = createMockTaskDetail({
        status: 'discussing',
        id: 'task-stream-id-xyz',
      })

      render(<DiscussionDetailPanel task={task} />)

      const streamElement = screen.getByTestId('discussion-stream-mock')
      expect(streamElement.getAttribute('data-discussion-id')).toBe('task-stream-id-xyz')
    })
  })
})
