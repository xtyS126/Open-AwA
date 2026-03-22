export interface BillingUsage {
  call_id: string
  user_id: string | null
  session_id: string | null
  provider: string
  model: string
  content_type: string
  input_tokens: number
  output_tokens: