import api from './api'

export interface Experience {
  id: number
  experience_type: 'strategy' | 'method' | 'error_pattern' | 'tool_usage' | 'context_handling'
  title: string
  content: string
  trigger_conditions: string
  confidence: number
  source_task: string
  usage_count: number
  success_count: number
  created_at: string
  last_access: string
  metadata?: Record<string, unknown>
}

export interface ExperienceSearchParams {
  experience_type?: string
  min_confidence?: number
  source_task?: string
  sort_by?: string
  order?: 'asc' | 'desc'
  page?: number
  limit?: number
}

export interface ExperienceStats {
  total_experiences: number
  type_distribution: Record<string, number>
  avg_confidence: number
  avg_success_rate: number
  total_usage: number
  total_success: number
  top_experiences: Array<{ id: number; title: string; usage_count: number }>
}

export interface ExtractionLog {
  id: number
  session_id: string
  task_summary: string
  trigger: string
  quality: number
  reviewed: boolean
  created_at: string
}

export const experiencesAPI = {
  getExperiences: (params: ExperienceSearchParams = {}) =>
    api.get('/experiences', { params }),

  getExperience: (id: number) =>
    api.get(`/experiences/${id}`),

  createExperience: (data: Partial<Experience>) =>
    api.post('/experiences', data),

  updateExperience: (id: number, data: Partial<Experience>) =>
    api.put(`/experiences/${id}`, data),

  deleteExperience: (id: number) =>
    api.delete(`/experiences/${id}`),

  extractExperience: (data: {
    session_id: string
    user_goal: string
    execution_steps: Array<{ action: string; result: string }>
    final_result: string
    status: string
  }) =>
    api.post('/experiences/extract', data),

  searchExperiences: (query: string, experience_type?: string, min_confidence?: number) =>
    api.get('/experiences/search', {
      params: { query, experience_type, min_confidence }
    }),

  getStats: () =>
    api.get('/experiences/stats/summary'),

  getExtractionLogs: (page: number = 1, limit: number = 20) =>
    api.get('/experiences/logs', { params: { page, limit } }),

  reviewExperience: (id: number, approved: boolean) =>
    api.put(`/experiences/${id}/review`, null, { params: { approved } }),
}
