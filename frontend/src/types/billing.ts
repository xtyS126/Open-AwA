export interface BillingUsage {
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

export interface ModelPrice {
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

export interface Budget {
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

export interface CostStats {
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

export interface ModelCost {
  provider: string
  model: string
  input_tokens: number
  output_tokens: number
  cost: number
  call_count: number
}

export interface TokensAndCost {
  tokens: number
  cost: number
}

export interface DailyTrend {
  date: string
  cost: number
  input_tokens: number
  output_tokens: number
}

export interface RetentionSettings {
  retention_days: number
  total_records: number
  oldest_record: string | null
  newest_record: string | null
}

export interface RetentionUpdate {
  retention_days: number
  cleanup?: boolean
}

export interface RetentionUpdateResult {
  success: boolean
  old_retention_days: number
  new_retention_days: number
  deleted_records: number
}

export interface PriceUpdate {
  input_price?: number
  output_price?: number
  currency?: string
  cache_hit_price?: number
}
