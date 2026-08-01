/**
 * 提示词 API 模块。封装提示词列表与管理端点。自 api.ts 拆分而来。
 */
import { api } from './client'
import type { ApiPayload, PromptItem, PromptsListResponse } from './types'

export const promptsAPI = {
  getAll: () => api.get<PromptsListResponse>('/prompts'),
  getActive: () => api.get<PromptItem>('/prompts/active'),
  getOne: (id: string) => api.get<PromptItem>(`/prompts/${id}`),
  create: (prompt: ApiPayload) => api.post<PromptItem>('/prompts', prompt),
  update: (id: string, prompt: ApiPayload) => api.put<PromptItem>(`/prompts/${id}`, prompt),
  delete: (id: string) => api.delete<{ ok: boolean; message?: string }>(`/prompts/${id}`),
}
