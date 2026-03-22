import api from './api'

export interface ModelConfiguration {
  id: number
  provider: string
  model: string
  display_name: string | null
  description: string | null
  is_active: boolean
  is_default: boolean
  sort_order: number
  created_at: string | null
  updated_at: string | null
}

export interface ModelProvider {
  id: string
  name: string
}

export interface ProviderModel {
  id: number
  provider: string
  model: string
  input_price: number
  output_price: number
  currency: string
  context_window: number | null
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
    api_key?: string
    api_endpoint?: string
    is_active?: boolean
    is_default?: boolean
    sort_order?: number
  }) => api.post('/billing/configurations', data),

  updateConfiguration: (configId: number, data: {
    provider?: string
    model?: string
    display_name?: string
    description?: string
    api_key?: string
    api_endpoint?: string
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

  getModelsByProvider: (provider: string) =>
    api.get(`/billing/models-by-provider/${provider}`),

  getModels: (params?: { provider?: string }) =>
    api.get('/billing/models', { params }),
}
