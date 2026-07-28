import '@testing-library/jest-dom/vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import UsageDetailDrawer from '@/features/billing/components/UsageDetailDrawer'
import type { UsageRecord } from '@/features/billing/billingApi'

// 构造完整的测试用量记录（覆盖所有新增字段）
const makeRecord = (overrides: Partial<UsageRecord> = {}): UsageRecord => ({
  call_id: 'call-abc-123',
  user_id: 'user-1',
  session_id: 'session-1',
  provider: 'openai',
  model: 'gpt-4o-mini',
  content_type: 'chat',
  input_tokens: 1200,
  output_tokens: 800,
  input_cost: 0.1,
  output_cost: 0.1345,
  total_cost: 0.2345,
  currency: 'USD',
  cache_hit: true,
  duration_ms: 245,
  created_at: '2026-07-10T08:00:00Z',
  cache_read_tokens: 500,
  cache_write_tokens: 200,
  cache_read_cost: 0.005,
  cache_write_cost: 0.003,
  thoughts_tokens: 150,
  method: 'api_usage',
  estimated: false,
  extra_data: { request_id: 'req-001', tool_calls: 2 },
  ...overrides,
})

describe('UsageDetailDrawer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not render when open is false', () => {
    const onClose = vi.fn()
    const { container } = render(
      <UsageDetailDrawer record={makeRecord()} open={false} onClose={onClose} />
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('renders empty state when record is null and open is true', () => {
    const onClose = vi.fn()
    render(<UsageDetailDrawer record={null} open={true} onClose={onClose} />)
    expect(screen.getByText('暂无数据')).toBeInTheDocument()
  })

  it('renders basic info section correctly', () => {
    const onClose = vi.fn()
    render(<UsageDetailDrawer record={makeRecord()} open={true} onClose={onClose} />)

    // 标题
    expect(screen.getByText('用量调用详情')).toBeInTheDocument()
    // 基本信息
    expect(screen.getByText('基本信息')).toBeInTheDocument()
    expect(screen.getByText('openai')).toBeInTheDocument()
    expect(screen.getByText('gpt-4o-mini')).toBeInTheDocument()
    expect(screen.getByText('chat')).toBeInTheDocument()
    expect(screen.getByText('call-abc-123')).toBeInTheDocument()
    expect(screen.getByText(/245 ms/)).toBeInTheDocument()
  })

  it('renders token breakdown section correctly', () => {
    const onClose = vi.fn()
    render(<UsageDetailDrawer record={makeRecord()} open={true} onClose={onClose} />)

    expect(screen.getByText('Token 明细')).toBeInTheDocument()
    // 输入/输出 token
    expect(screen.getByText('1.2K')).toBeInTheDocument() // 1200 -> 1.2K
    expect(screen.getByText('800')).toBeInTheDocument()
    // 缓存 token
    expect(screen.getByText('500')).toBeInTheDocument() // cache_read
    expect(screen.getByText('200')).toBeInTheDocument() // cache_write
    expect(screen.getByText('150')).toBeInTheDocument() // thoughts
  })

  it('renders cost breakdown section correctly', () => {
    const onClose = vi.fn()
    render(<UsageDetailDrawer record={makeRecord()} open={true} onClose={onClose} />)

    expect(screen.getByText('成本分解')).toBeInTheDocument()
    // 缓存成本合计 = 0.005 + 0.003 = 0.008
    expect(screen.getByText('$0.008000')).toBeInTheDocument()
    // 总成本
    expect(screen.getByText('$0.234500')).toBeInTheDocument()
  })

  it('renders method tag and exact precision badge', () => {
    const onClose = vi.fn()
    render(<UsageDetailDrawer record={makeRecord()} open={true} onClose={onClose} />)

    expect(screen.getByText('计数方法')).toBeInTheDocument()
    expect(screen.getByText('API')).toBeInTheDocument() // method=api_usage -> API
    expect(screen.getByText('精确')).toBeInTheDocument() // estimated=false -> 精确
  })

  it('renders estimated badge when estimated is true', () => {
    const onClose = vi.fn()
    const record = makeRecord({ estimated: true, method: 'tiktoken' })
    render(<UsageDetailDrawer record={record} open={true} onClose={onClose} />)

    expect(screen.getByText('tiktoken')).toBeInTheDocument()
    expect(screen.getByText('估算')).toBeInTheDocument()
  })

  it('renders extra_data as formatted JSON', () => {
    const onClose = vi.fn()
    render(<UsageDetailDrawer record={makeRecord()} open={true} onClose={onClose} />)

    expect(screen.getByText('附加数据 (extra_data)')).toBeInTheDocument()
    // JSON 格式化后应包含 request_id
    expect(screen.getByText(/request_id/)).toBeInTheDocument()
    expect(screen.getByText(/req-001/)).toBeInTheDocument()
  })

  it('renders empty extra_data message when extra_data is undefined', () => {
    const onClose = vi.fn()
    const record = makeRecord({ extra_data: undefined })
    render(<UsageDetailDrawer record={record} open={true} onClose={onClose} />)

    expect(screen.getByText('暂无附加数据')).toBeInTheDocument()
  })

  it('shows dash for missing optional token fields', () => {
    const onClose = vi.fn()
    const record = makeRecord({
      cache_read_tokens: 0,
      cache_write_tokens: undefined,
      thoughts_tokens: 0,
    })
    render(<UsageDetailDrawer record={record} open={true} onClose={onClose} />)

    // 0 或 undefined 的 token 字段应显示为 "-"
    // 注意：input/output 是必填字段，不显示 "-"
    const dashes = screen.getAllByText('-')
    expect(dashes.length).toBeGreaterThanOrEqual(3) // cache_read, cache_write, thoughts
  })

  it('calls onClose when close button is clicked', () => {
    const onClose = vi.fn()
    render(<UsageDetailDrawer record={makeRecord()} open={true} onClose={onClose} />)

    const closeBtn = screen.getByLabelText('关闭')
    fireEvent.click(closeBtn)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose when overlay is clicked', () => {
    const onClose = vi.fn()
    const { container } = render(
      <UsageDetailDrawer record={makeRecord()} open={true} onClose={onClose} />
    )

    // 点击遮罩层（非抽屉主体）触发关闭
    const overlay = container.firstElementChild as HTMLElement
    fireEvent.click(overlay)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose when ESC key is pressed', () => {
    const onClose = vi.fn()
    render(<UsageDetailDrawer record={makeRecord()} open={true} onClose={onClose} />)

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('handles CNY currency correctly', () => {
    const onClose = vi.fn()
    const record = makeRecord({
      currency: 'CNY',
      total_cost: 1.5,
      cache_read_cost: 0.05,
      cache_write_cost: 0.02,
    })
    render(<UsageDetailDrawer record={record} open={true} onClose={onClose} />)

    // CNY 应显示 ¥ 符号
    expect(screen.getByText('¥1.500000')).toBeInTheDocument()
    // 缓存读取成本
    expect(screen.getByText('¥0.050000')).toBeInTheDocument()
    // 缓存写入成本
    expect(screen.getByText('¥0.020000')).toBeInTheDocument()
    // 缓存成本合计 = 0.05 + 0.02 = 0.07
    expect(screen.getByText('¥0.070000')).toBeInTheDocument()
  })

  it('renders all method label variants', () => {
    const onClose = vi.fn()
    const methods: Array<{ method: NonNullable<UsageRecord['method']>; label: string }> = [
      { method: 'api_usage', label: 'API' },
      { method: 'stream', label: '流式' },
      { method: 'tiktoken', label: 'tiktoken' },
      { method: 'ratio', label: '字符比率' },
    ]

    for (const { method, label } of methods) {
      const { unmount } = render(
        <UsageDetailDrawer record={makeRecord({ method })} open={true} onClose={onClose} />
      )
      expect(screen.getByText(label)).toBeInTheDocument()
      unmount()
    }
  })
})
