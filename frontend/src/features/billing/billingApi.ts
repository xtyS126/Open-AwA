import api from '@/shared/api/api'

// 用量记录（与 billing.ts 中 BillingUsage 等价，取并集为权威定义）
// 新增字段（cache_read_tokens / cache_write_tokens / thoughts_tokens / method / estimated / extra_data）
// 由后端 usage_tracker.record_llm_call() 写入，对应 Task 7 的前端展示增强
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
  // 新增字段：缓存与思考 token 明细（后端写入 metadata，API 可能返回）
  cache_read_tokens?: number
  cache_write_tokens?: number
  cache_read_cost?: number
  cache_write_cost?: number
  thoughts_tokens?: number
  // 计数方法：api_usage=API返回 / stream=流式累计 / tiktoken=本地分词 / ratio=字符比率
  method?: 'api_usage' | 'stream' | 'tiktoken' | 'ratio'
  // 是否为估算值（true=估算，false=精确）
  estimated?: boolean
  // 附加数据（后端 metadata.extra_data，用于审计与诊断）
  extra_data?: Record<string, unknown>
}

// 模型定价（合并自 billing.ts 的 ModelPrice，覆盖多模态字段）
// 新增字段（cache_read_price / cache_write_price / per_image_price / per_minute_price /
// owned_by / family / capabilities / input_modalities / output_modalities / max_output_tokens）
// 对应后端 ModelPricing 表扩展，由 catalog_sync 从 models.dev / openrouter.ai 同步
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
  // 新增字段：缓存定价（每百万 token）
  cache_read_price?: number
  cache_write_price?: number
  // 新增字段：多模态计量定价
  per_image_price?: number
  per_minute_price?: number
  // 新增字段：模型归属与族系（用于目录分组与筛选）
  owned_by?: string
  family?: string
  // 新增字段：能力标签与模态支持（catalog_sync 同步）
  capabilities?: string[]
  input_modalities?: string[]
  output_modalities?: string[]
  max_output_tokens?: number
}

// 模型目录同步结果（POST /api/billing/sync-catalog 返回体）
// 对应后端 billing.routers.sync_model_catalog，admin 权限触发
export interface CatalogSyncResult {
  // 后端返回 success 字段表示同步是否成功
  success?: boolean
  // 新增的模型数量
  added: number
  // 更新的模型数量
  updated: number
  // 失效（标记为 inactive）的模型数量
  removed: number
  // 跳过未变更的模型数量
  skipped: number
  // 同步完成时间（ISO 8601 字符串）
  synced_at: string
  // 是否为 dry-run 模式（仅模拟不落库）
  dry_run?: boolean
  // 可选的人类可读消息
  message?: string
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

  // 委托给顶层 getModels 函数，保持单一数据源（modelsApi.ts 通过 re-export 复用）
  getModels: (params?: { provider?: string }) => getModels(params),

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

  // 触发模型目录同步（admin 权限）
  // 从 models.dev / openrouter.ai 拉取最新模型列表与定价，合并写入本地定价表
  // 返回同步统计：added / updated / removed / skipped / synced_at
  syncModelCatalog: () =>
    api.post<CatalogSyncResult>('/billing/sync-catalog'),
}

// 顶层函数形式的同步入口，便于在非 billingAPI 命名空间下复用
// 调用方式：const result = await syncModelCatalog()
// 错误处理：失败时抛出 AxiosError，由调用方捕获并展示 toast
export async function syncModelCatalog(): Promise<CatalogSyncResult> {
  const response = await api.post<CatalogSyncResult>('/billing/sync-catalog')
  return response.data
}

// 顶层 getModels 函数：单一数据源，供 billingAPI.getModels 委托与 modelsApi.ts re-export 复用
// 调用方式：const response = await getModels({ provider: 'openai' })
// 返回：AxiosResponse<{ models: ModelPricing[]; ... }>
// 设计目的：消除 billingApi.ts 与 modelsApi.ts 中 getModels 的重复定义，避免行为分叉
export function getModels(params?: { provider?: string }) {
  return api.get('/billing/models', { params })
}
