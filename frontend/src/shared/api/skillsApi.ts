/**
 * 技能 API 模块。封装技能列表、解析上传等端点。自 api.ts 拆分而来。
 */
import { api } from './client'
import type { ApiPayload, SkillItem, SkillsListResponse, SkillParseUploadResponse } from './types'

export const skillsAPI = {
  getAll: () => api.get<SkillsListResponse>('/skills'),
  getOne: (id: string) => api.get<SkillItem>(`/skills/${id}`),
  install: (skill: ApiPayload) => api.post<SkillItem>('/skills', skill),
  uninstall: (id: string) => api.delete<{ ok: boolean; message?: string }>(`/skills/${id}`),
  toggle: (id: string) => api.put<SkillItem>(`/skills/${id}/toggle`),
  parseUpload: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return api.post<SkillParseUploadResponse>('/skills/parse-upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
  },
}
