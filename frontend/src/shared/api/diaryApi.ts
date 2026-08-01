/**
 * 日记 API 模块。封装日记生成与查询端点。自 api.ts 拆分而来。
 */
import { api } from './client'

export interface DiaryGenerateResponse {
  success: boolean
  file_path?: string
  content?: string
  logical_date?: string
  error?: string
}

export interface DiaryListResponse {
  success: boolean
  diaries: Array<{ name: string; date: string; size: number }>
  count: number
}

export interface DiaryReadResponse {
  success: boolean
  date: string
  content: string
}

export const diaryAPI = {
  async generate(): Promise<DiaryGenerateResponse> {
    const response = await api.post('/diary/generate')
    return response.data
  },

  async list(): Promise<DiaryListResponse> {
    const response = await api.get('/diary/list')
    return response.data
  },

  async get(date: string): Promise<DiaryReadResponse> {
    const response = await api.get(`/diary/${date}`)
    return response.data
  },
}

/**
 * 问题反馈 API。
 * 提交用户反馈到后端，后端落盘为 markdown 文件并返回 file_id。
 * 注意：api.post 返回 AxiosResponse，这里通过 .then(r => r.data) 直接返回业务数据，
 * 便于调用方处理与单元测试 mock。
 */
