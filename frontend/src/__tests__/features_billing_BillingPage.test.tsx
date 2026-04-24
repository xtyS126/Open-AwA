import '@testing-library/jest-dom/vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, it, expect, vi } from 'vitest'
import BillingPage from '@/features/billing/BillingPage'
import { BrowserRouter } from 'react-router-dom'
import { BILLING_USAGE_UPDATED_EVENT } from '@/shared/events/billingEvents'

const billingMocks = vi.hoisted(() => ({
  getCostStatistics: vi.fn(),
  getUsage: vi.fn(),
  getBudget: vi.fn(),
  getReport: vi.fn(),
}))

vi.mock('@/features/billing/billingApi', () => ({
  billingAPI: billingMocks,
}))

describe('BillingPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    billingMocks.getCostStatistics.mockResolvedValue({
      data: {
        period: 'monthly',
        period_start: '2026-04-01T00:00:00',
        period_end: '2026-04-30T00:00:00',
        total_cost: 0.2345,
        total_input_tokens: 1200,
        total_output_tokens: 800,
        total_calls: 4,
        by_model: [
          { provider: 'openai', model: 'gpt-4o-mini', input_tokens: 1200, output_tokens: 800, cost: 0.2345, call_count: 4 },
        ],
        by_content_type: {
          chat: { tokens: 2000, cost: 0.2345 },
        },
        trend: [
          { date: '2026-04-19', cost: 0.2345, input_tokens: 1200, output_tokens: 800 },
        ],
        currency: 'USD',
      },
    })
    billingMocks.getUsage.mockResolvedValue({
      data: {
        records: [
          {
            call_id: 'usage-1',
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
            cache_hit: false,
            duration_ms: 245,
            created_at: '2026-04-19T03:00:00',
          },
        ],
      },
    })
    billingMocks.getBudget.mockResolvedValue({ data: null })
    billingMocks.getReport.mockResolvedValue({ data: 'csv' })
  })

  it('renders billing data and sync status', async () => {
    render(<BrowserRouter><BillingPage /></BrowserRouter>)
    expect(await screen.findByText('用量计费')).toBeInTheDocument()
    expect(await screen.findByText('已开启聊天用量联动')).toBeInTheDocument()
    expect(screen.getByText('gpt-4o-mini')).toBeInTheDocument()
  })

  it('receives billing usage update event and refreshes silently', async () => {
    render(<BrowserRouter><BillingPage /></BrowserRouter>)

    await waitFor(() => expect(billingMocks.getCostStatistics).toHaveBeenCalledTimes(1))

    await act(async () => {
      window.dispatchEvent(new CustomEvent(BILLING_USAGE_UPDATED_EVENT, {
        detail: { callId: 'usage-2', provider: 'openai', model: 'gpt-4o-mini' },
      }))
    })

    await waitFor(() => expect(billingMocks.getCostStatistics).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(screen.getByText('已开启聊天用量联动')).toBeInTheDocument())
  })
})
