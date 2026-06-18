/** AI 角色性格参数 */
export interface RolePersonality {
  tone: 'professional' | 'casual' | 'friendly' | 'strict'
  verbosity: 'concise' | 'normal' | 'detailed'
  creativity: number
  formality: number
}

/** AI 角色专长领域 */
export interface RoleExpertise {
  domains: string[]
  languages: string[]
  specialties: string[]
}

/** AI 角色模型配置 */
export interface RoleModelConfig {
  preferred_model: string
  fallback_model: string
  temperature: number
  max_tokens: number
}

/** AI 角色定义 */
export interface AgentRole {
  id: string
  name: string
  description: string
  avatar_url: string
  system_prompt: string
  personality: RolePersonality
  expertise: RoleExpertise
  knowledge_base_ids: string[]
  allowed_tools: string[]
  allowed_skills: string[]
  model_config: RoleModelConfig
  creator_id: number | null
  is_public: boolean
  usage_count: number
  is_preset: boolean
  created_at: string
  updated_at: string
}

/** 创建角色请求 */
export interface RoleCreateRequest {
  name: string
  description?: string
  avatar_url?: string
  system_prompt: string
  personality?: Partial<RolePersonality>
  expertise?: Partial<RoleExpertise>
  knowledge_base_ids?: string[]
  allowed_tools?: string[]
  allowed_skills?: string[]
  model_config_override?: Partial<RoleModelConfig>
  is_public?: boolean
}

/** 更新角色请求 */
export interface RoleUpdateRequest extends Partial<RoleCreateRequest> {}

/** 角色激活响应 */
export interface RoleActivateResponse {
  status: string
  role_id: string
  role_name: string
  session_id: string
  system_prompt: string
  personality: RolePersonality
  allowed_tools: string[]
  allowed_skills: string[]
  model_config: RoleModelConfig
}
