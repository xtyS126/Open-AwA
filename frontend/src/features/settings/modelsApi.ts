// 直接从 client 导入 axios 实例，避免经由 api.ts barrel 把全部业务 API 模块拉入页面关键路径
import { api } from '@/shared/api/client'

export interface ModelConfiguration {
  id: number
  provider: string
  model: string
  display_name: string | null
  description: string | null
  icon?: string | null
  api_endpoint?: string | null
  base_url?: string | null
  api_key?: string | null
  has_api_key?: boolean
  // 密钥状态：active 已配置且可用 / stale 旧算法密文已失效 / missing 未配置
  api_key_status?: 'active' | 'stale' | 'missing'
  selected_models?: string[]
  is_active: boolean
  is_default: boolean
  sort_order: number
  // Model parameter fields
  temperature?: number | null
  top_k?: number | null
  top_p?: number | null
  max_tokens_limit?: number | null
  frequency_penalty?: number | null
  presence_penalty?: number | null
  timeout?: number | null
  retry_count?: number | null
  // Model capability flags
  supports_temperature?: boolean
  supports_top_k?: boolean
  supports_vision?: boolean
  is_multimodal?: boolean
  // 模态标签：输入/输出方向各自支持的模态列表
  input_modality?: string[]
  output_modality?: string[]
  // 生图模型标记：标记后该配置仅用于图像生成（SD / GPT-Image / Qwen-Image 系列），不参与聊天
  is_image_generation?: boolean
  // 生图模型用途与限制描述：供 AI 在生图时准确选择模型
  image_generation_usage?: string | null
  // Model metadata
  model_spec?: ModelSpec | null
  status?: string
  created_at: string | null
  updated_at: string | null
}

export interface ModelSpec {
  context_window?: number
  max_output_tokens?: number
  supports_function_calling?: boolean
  supports_streaming?: boolean
  supports_vision?: boolean
  supports_audio?: boolean
  input_modality?: string[]
  output_modality?: string[]
}

export interface ModelCapabilities {
  supports_temperature: boolean
  supports_top_k: boolean
  supports_vision: boolean
  is_multimodal: boolean
  supports_function_calling: boolean
  supports_streaming: boolean
  input_modality?: string[]
  output_modality?: string[]
}

export interface ModelCapabilitiesResponse {
  config_id: number
  provider: string
  model: string
  capabilities: ModelCapabilities
  defaults: {
    temperature: number
    top_k: number
    max_tokens: number
    frequency_penalty: number
    presence_penalty: number
    timeout: number
    retry_count: number
  }
  limits: {
    temperature_min: number
    temperature_max: number
    top_k_min: number
    top_k_max: number
    max_tokens_min: number
    max_tokens_max: number
    frequency_penalty_min: number
    frequency_penalty_max: number
    presence_penalty_min: number
    presence_penalty_max: number
    timeout_min: number
    timeout_max: number
    retry_count_min: number
    retry_count_max: number
  }
}

export interface ModelParameterUpdate {
  temperature?: number | null
  top_k?: number | null
  top_p?: number | null
  max_tokens_limit?: number | null
  frequency_penalty?: number | null
  presence_penalty?: number | null
  timeout?: number | null
  retry_count?: number | null
}

export interface ModelProvider {
  id: string
  name: string
  display_name?: string
  icon?: string | null
  api_endpoint?: string | null
  base_url?: string | null
  has_api_key?: boolean
  // 密钥状态：active 已配置且可用 / stale 旧算法密文已失效 / missing 未配置
  api_key_status?: 'active' | 'stale' | 'missing'
  selected_models?: string[]
  configuration_count?: number
  source?: 'database' | 'pricing_data'
  model_count?: number
  models?: ProviderCatalogModel[]
}

/** 供应商目录中的模型条目 */
export interface ProviderCatalogModel {
  name: string
  input_price: number
  output_price: number
  currency: string
  context_window: number | null
}

/** 供应商目录响应 */
export interface ProviderCatalogResponse {
  providers: ModelProvider[]
  total: number
}

export interface ProviderDetailResponse {
  provider: ModelProvider
  configuration: ModelConfiguration | null
}

// Ollama 模型发现结果
export interface OllamaModel {
  name: string
  size: number
  modified_at: string
  digest: string
}

export interface OllamaDiscoverResponse {
  success: boolean
  provider: string
  base_url: string
  models: OllamaModel[]
  count: number
}

// 提供商连接状态
export interface ProviderConnectionStatus {
  provider: string
  status: 'connected' | 'auth_error' | 'timeout' | 'unreachable' | 'unconfigured' | 'error'
  message: string
  display_name?: string
}

// 连通性测试结果
export interface ConnectivityTestResult {
  success: boolean
  model_count?: number | null
  error_message?: string | null
  latency_ms: number
  provider: string
}

export interface ProvidersStatusResponse {
  success: boolean
  providers: ProviderConnectionStatus[]
}

export interface ProviderModel {
  id: number
  provider: string
  model: string
  input_price: number
  output_price: number
  currency: string
  context_window: number | null
  selected?: boolean
}

export interface ProviderModelsResponse {
  success: boolean
  provider: string
  models: ProviderModel[]
  selected_models: string[]
  source?: 'remote' | 'local'
  error?: {
    code: string
    message: string
    detail?: string
  } | null
}

export const modelsAPI = {
  getConfigurations: () =>
    api.get('/billing/configurations'),

  getConfiguration: (configId: number) =>
    api.get(`/billing/configurations/${configId}`),

  createConfiguration: (data: {
    provider: string
    model: string
    display_name?: string
    description?: string
    icon?: string
    api_key?: string
    api_endpoint?: string
    selected_models?: string[]
    is_active?: boolean
    is_default?: boolean
    sort_order?: number
    input_modality?: string
    output_modality?: string
    is_image_generation?: boolean
    image_generation_usage?: string
  }) => api.post('/billing/configurations', data),

  updateConfiguration: (configId: number, data: {
    provider?: string
    model?: string
    display_name?: string
    description?: string
    icon?: string
    api_key?: string
    api_endpoint?: string
    selected_models?: string[]
    is_active?: boolean
    is_default?: boolean
    sort_order?: number
    input_modality?: string
    output_modality?: string
    is_image_generation?: boolean
    image_generation_usage?: string
  }) => api.put(`/billing/configurations/${configId}`, data),

  deleteConfiguration: (configId: number) =>
    api.delete(`/billing/configurations/${configId}`),

  setDefaultConfiguration: (configId: number) =>
    api.put(`/billing/configurations/${configId}/set-default`),

  updateParameters: (configId: number, params: ModelParameterUpdate) =>
    api.put(`/billing/configurations/${configId}/parameters`, params),

  getCapabilities: (configId: number) =>
    api.get<ModelCapabilitiesResponse>(`/billing/configurations/${configId}/capabilities`),

  resetParameters: (configId: number) =>
    api.post(`/billing/configurations/${configId}/reset-parameters`),

  batchUpdateStatus: (configIds: number[], status: string) =>
    api.put('/billing/configurations/batch-status', { config_ids: configIds, status }),

  getProviders: () =>
    api.get('/billing/providers'),

  /** 获取供应商预填充目录（合并数据库和 pricing_data.json） */
  getProviderCatalog: () =>
    api.get<ProviderCatalogResponse>('/billing/provider-catalog'),

  getProviderDetail: (provider: string) =>
    api.get(`/billing/providers/${provider}`),

  deleteProvider: (provider: string) =>
    api.delete(`/billing/providers/${provider}`),

  updateProviderSelectedModels: (provider: string, data: { selected_models: string[] }) =>
    api.put(`/billing/providers/${provider}/selected-models`, data),

  getModelsByProvider: (provider: string, payload?: { api_endpoint?: string; api_key?: string }) =>
    api.post(`/billing/models-by-provider/${provider}`, payload ?? {}),

  // Ollama 本地模型发现
  discoverOllamaModels: () =>
    api.get<OllamaDiscoverResponse>('/models/ollama'),

  // 获取所有提供商连接状态
  getProvidersStatus: () =>
    api.get<ProvidersStatusResponse>('/models/providers'),

  // ── Provider 凭据 API ──────────────────────────────────────────

  saveProviderCredential: (provider: string, data: {
    api_key?: string
    api_endpoint?: string
    display_name?: string
    icon?: string
  }) => api.put(`/billing/credentials/${provider}`, data),

  getProviderCredential: (provider: string) =>
    api.get(`/billing/credentials/${provider}`),

  /** 获取脱敏的 API Key */
  getMaskedApiKey: (provider: string) =>
    api.get<{ masked_api_key: string | null; has_api_key: boolean }>(`/billing/credentials/${provider}/masked-key`),

  /** 获取明文 API Key（仅供前端"显示"按钮主动调用） */
  getPlainApiKey: (provider: string) =>
    api.get<{ api_key: string | null; has_api_key: boolean; api_key_status: string }>(`/billing/credentials/${provider}/plain-key`),

  /** 测试供应商连通性 */
  testProviderConnectivity: (provider: string, apiKey: string, baseUrl?: string) =>
    api.post<ConnectivityTestResult>('/system/connectivity-test', {
      provider,
      api_key: apiKey,
      base_url: baseUrl || undefined,
    }),
}

// getModels 已收敛至 billingApi.ts 的顶层 getModels 函数，避免与 billingAPI.getModels 重复定义
// 此处通过 re-export 保持向后兼容：既有 `import { getModels } from '@/features/settings/modelsApi'` 仍可用
export { getModels } from '@/features/billing/billingApi'
