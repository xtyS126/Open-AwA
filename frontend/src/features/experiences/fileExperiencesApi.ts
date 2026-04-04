import api from '@/shared/api/api'

export interface ExperienceFileSummary {
  file_name: string
  title: string
  updated_at: string
  size: number
  summary: string
}

export interface ExperienceFileDetail {
  file_name: string
  title: string
  updated_at: string
  size: number
  content: string
}

export interface ExperienceFileSaveResponse {
  file_name: string
  updated_at: string
  size: number
}

export const fileExperiencesApi = {
  listFiles: () => api.get<ExperienceFileSummary[]>('/experience-files'),

  getFileDetail: (fileName: string) =>
    api.get<ExperienceFileDetail>(`/experience-files/${encodeURIComponent(fileName)}`),

  saveFile: (fileName: string, content: string) =>
    api.put<ExperienceFileSaveResponse>(`/experience-files/${encodeURIComponent(fileName)}`, { content }),
}
