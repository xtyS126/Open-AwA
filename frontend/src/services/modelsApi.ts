import api from './api'

export interface ModelConfiguration {
  id: number
  provider: string
  model: string
  display_name: string | null
  description: string | null
  icon?: string | null
  api_endpoint?: string | null
  api_key?: string | null
  has_api_key?: boolean
  selected_models?: string[]
  is_active: boolean
  is_default: boolean
  sort_order: number
  created_at: string | null
  updated_at: string | null
}

export interface ModelProvider {
  id: string
  name: string
  display_name?: string
  icon?: string | null
  api_endpoint?: string | null
  has_api_key?: boolean
  selected_models?: string[]
  configuration_count?: number
}

export interface ProviderDetailResponse {
  provider: ModelProvider
  configuration: ModelConfiguration
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
  }) => api.put(`/billing/configurations/${configId}`, data),

  deleteConfiguration: (configId: number) =>
    api.delete(`/billing/configurations/${configId}`),

  setDefaultConfiguration: (configId: number) =>
    api.put(`/billing/configurations/${configId}/set-default`),

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
}
