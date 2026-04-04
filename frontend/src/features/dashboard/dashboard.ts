export interface BehaviorStats {
  total_interactions: number
  total_tools_used: number
  average_response_time: number
  top_intents: Intent[]
  chart_data: ChartData[]
  date_range?: string
}

export interface Intent {
  intent: string
  count: number
  percentage?: number
}

export interface ChartData {
  day: string
  interactions: number
  [key: string]: string | number
}

export interface BillingStats {
  total_cost: number
  currency: string
  trend: CostTrend[]
  by_model: ModelUsage[]
}

export interface CostTrend {
  date: string
  cost: number
  input_tokens?: number
  output_tokens?: number
  [key: string]: string | number | undefined
}

export interface ModelUsage {
  provider: string
  model: string
  cost: number
  requests?: number
  [key: string]: string | number | undefined
}

export interface Provider {
  id: string
  name: string
}

export interface Plugin {
  id: string
  name: string
  version: string
  enabled: boolean
  description?: string
  [key: string]: string | number | boolean | undefined
}

export interface Skill {
  id: string
  name: string
  version: string
  enabled: boolean
  description?: string
  [key: string]: string | number | boolean | undefined
}
