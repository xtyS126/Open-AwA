import api from '@/shared/api/api'

// 用量记录（与 billing.ts 中 BillingUsage 等价，取并集为权威定义）
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

// 模型定价（合并自 billing.ts 的 ModelPrice，覆盖多模态字段）
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
  supports_vision: boolean
  is_multimodal: boolean
  input_modality?: string[]
  output_modality?: string[]
  updated_at: string | null
}

// 预算状态（合并自 billing.ts 的 Budget，budget_type 收敛为 union 类型）
export interface BudgetStatus {
  has_budget_configured: boolean
  budget_type?: 'global' | 'user' | 'project' | 'model'
  max_amount?: number
  current_usage?: number
  remaining?: number
  usage_percentage?: number
  warning_threshold?: number
  period_type?: 'daily' | 'weekly' | 'monthly' | 'yearly'
  currency?: string
  is_warning?: boolean
  is_exceeded?: boolean
  message?: string
}

// 单个模型的成本汇总（从 CostStatistics.by_model 抽出命名）
export interface ModelCost {
  provider: string
  model: string
  input_tokens: number
  output_tokens: number
  cost: number
  call_count: number
}

// 单个内容类型的 token 与成本（从 CostStatistics.by_content_type 抽出命名）
export interface TokensAndCost {
  tokens: number
  cost: number
}

// 单日趋势数据（从 CostStatistics.trend 抽出命名）
export interface DailyTrend {
  date: string
  cost: number
  input_tokens: number
  output_tokens: number
}

// 成本统计（合并自 billing.ts 的 CostStats，嵌套类型引用命名导出）
export interface CostStatistics {
  period: string
  period_start: string
  period_end: string
  total_cost: number
  total_input_tokens: number
  total_output_tokens: number
  total_calls: number
  by_model: ModelCost[]
  by_content_type: Record<string, TokensAndCost>
  trend: DailyTrend[]
  currency: string
}

// 保留期配置（与 billing.ts 中 RetentionSettings 等价）
export interface RetentionConfig {
  retention_days: number
  total_records: number
  oldest_record: string | null
  newest_record: string | null
}

// 更新保留期请求体（从 billingAPI.updateRetention 参数抽出命名）
export interface RetentionUpdate {
  retention_days: number
  cleanup?: boolean
}

// 更新保留期响应（与 billing.ts 中 RetentionUpdateResult 等价）
export interface RetentionUpdateResponse {
  success: boolean
  old_retention_days: number
  new_retention_days: number
  deleted_records: number
}

// 更新模型定价请求体（从 billingAPI.updateModelPricing 参数抽出命名）
export interface PriceUpdate {
  input_price?: number
  output_price?: number
  currency?: string
  cache_hit_price?: number
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
    period?: 'daily' | 'weekly' | 'monthly' | 'yearly'
  }) => api.get('/billing/cost', { params }),

  getModels: (params?: { provider?: string }) =>
    api.get('/billing/models', { params }),

  updateModelPricing: (modelId: number, data: PriceUpdate) =>
    api.put(`/billing/models/${modelId}`, data),

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

  updateRetention: (data: RetentionUpdate) =>
    api.post('/billing/retention', data),
}
