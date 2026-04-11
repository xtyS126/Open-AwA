import api from '@/shared/api/api'

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
  selected_models?: string[]
  max_tokens?: number | null
  is_active: boolean
  is_default: boolean
  sort_order: number
  // Model parameter fields
  temperature?: number | null
  top_k?: number | null
  top_p?: number | null
  max_tokens_limit?: number | null
  // Model capability flags
  supports_temperature?: boolean
  supports_top_k?: boolean
  supports_vision?: boolean
  is_multimodal?: boolean
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
}

export interface ModelCapabilities {
  supports_temperature: boolean
  supports_top_k: boolean
  supports_vision: boolean
  is_multimodal: boolean
  supports_function_calling: boolean
  supports_streaming: boolean
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
  }
  limits: {
    temperature_min: number
    temperature_max: number
    top_k_min: number
    top_k_max: number
    max_tokens_min: number
    max_tokens_max: number
  }
}

export interface ModelParameterUpdate {
  temperature?: number | null
  top_k?: number | null
  top_p?: number | null
  max_tokens_limit?: number | null
}

export interface ModelProvider {
  id: string
  name: string
  display_name?: string
  icon?: string | null
  api_endpoint?: string | null
  base_url?: string | null
  has_api_key?: boolean
  selected_models?: string[]
  configuration_count?: number
}

export interface ProviderDetailResponse {
  provider: ModelProvider
  configuration: ModelConfiguration
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
    max_tokens?: number | null
    is_active?: boolean
    is_default?: boolean
    sort_order?: number
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
    max_tokens?: number | null
    is_active?: boolean
    is_default?: boolean
    sort_order?: number
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

  getProviderDetail: (provider: string) =>
    api.get(`/billing/providers/${provider}`),

  deleteProvider: (provider: string) =>
    api.delete(`/billing/providers/${provider}`),

  updateProviderSelectedModels: (provider: string, data: { selected_models: string[] }) =>
    api.put(`/billing/providers/${provider}/selected-models`, data),

  getModelsByProvider: (provider: string) =>
    api.get(`/billing/models-by-provider/${provider}`),

  getModels: (params?: { provider?: string }) =>
    api.get('/billing/models', { params }),

  // Ollama 本地模型发现
  discoverOllamaModels: () =>
    api.get<OllamaDiscoverResponse>('/models/ollama'),

  // 获取所有提供商连接状态
  getProvidersStatus: () =>
    api.get<ProvidersStatusResponse>('/models/providers'),
}
