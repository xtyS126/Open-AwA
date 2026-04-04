import api from '@/shared/api/api'

export interface UsageRecord {
  call_id: string
  user_id: string | null
  session_id: string | null
  provider: string
  model: string
  content_type: string
  input_tokens: number
  output_tokens: number
  input_cost: number
  output_cost: number
  total_cost: number
  currency: string
  cache_hit: boolean
  duration_ms: number
  created_at: string
}

export interface ModelPricing {
  id: number
  provider: string
  model: string
  input_price: number
  output_price: number
  currency: string
  cache_hit_price: number | null
  context_window: number | null
  is_active: boolean
  updated_at: string | null
}

export interface BudgetStatus {
  has_budget_configured: boolean
  budget_type?: string
  max_amount?: number
  current_usage?: number
  remaining?: number
  usage_percentage?: number
  warning_threshold?: number
  period_type?: string
  currency?: string
  is_warning?: boolean
  is_exceeded?: boolean
  message?: string
}

export interface CostStatistics {
  period: string
  period_start: string
  period_end: string
  total_cost: number
  total_input_tokens: number
  total_output_tokens: number
  total_calls: number
  by_model: Array<{
    provider: string
    model: string
    input_tokens: number
    output_tokens: number
    cost: number
    call_count: number
  }>
  by_content_type: Record<string, { tokens: number; cost: number }>
  trend: Array<{
    date: string
    cost: number
    input_tokens: number
    output_tokens: number
  }>
  currency: string
}

export interface RetentionConfig {
  retention_days: number
  total_records: number
  oldest_record: string | null
  newest_record: string | null
}

export interface RetentionUpdateResponse {
  success: boolean
  old_retention_days: number
  new_retention_days: number
  deleted_records: number
}

export const billingAPI = {
  getUsage: (params?: {
    user_id?: string
    session_id?: string
    provider?: string
    model?: string
    limit?: number
    offset?: number
  }) => api.get('/billing/usage', { params }),

  getCostStatistics: (params?: {
    user_id?: string
    period?: 'daily' | 'weekly' | 'monthly' | 'yearly' | 'all'
  }) => api.get('/billing/cost', { params }),

  getModels: (params?: { provider?: string }) =>
    api.get('/billing/models', { params }),

  updateModelPricing: (modelId: number, data: {
    input_price?: number
    output_price?: number
    currency?: string
    cache_hit_price?: number
  }) => api.put(`/billing/models/${modelId}`, data),

  getBudget: (userId: string) =>
    api.get('/billing/budget', { params: { user_id: userId } }),

  createBudget: (data: {
    budget_type: 'global' | 'user' | 'project' | 'model'
    max_amount: number
    scope_id?: string
    period_type?: 'daily' | 'weekly' | 'monthly' | 'yearly'
    currency?: string
    warning_threshold?: number
  }) => api.post('/billing/budget', data),

  updateBudget: (budgetId: number, data: {
    max_amount?: number
    period_type?: string
    currency?: string
    warning_threshold?: number
    is_active?: boolean
  }) => api.put(`/billing/budget/${budgetId}`, data),

  deleteBudget: (budgetId: number) =>
    api.delete(`/billing/budget/${budgetId}`),

  getReport: (params?: {
    user_id?: string
    period?: 'daily' | 'weekly' | 'monthly' | 'yearly' | 'all'
    format?: 'json' | 'csv'
  }) => api.get('/billing/report', { params }),

  getSessionUsage: (sessionId: string) =>
    api.get(`/billing/session/${sessionId}`),

  estimateCost: (params: {
    provider: string
    model: string
    text?: string
    num_images?: number
    audio_seconds?: number
    video_seconds?: number
  }) => api.get('/billing/estimate', { params }),

  initializePricing: () =>
    api.post('/billing/initialize-pricing'),

  getRetention: () =>
    api.get('/billing/retention'),

  updateRetention: (data: {
    retention_days: number
    cleanup?: boolean
  }) => api.post('/billing/retention', data),
}
