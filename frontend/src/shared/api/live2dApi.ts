/**
 * Live2D 模型 API 模块 —— 封装 /api/pets/live2d 端点的后端通信。
 * 与 petsApi.ts 一致的风格，使用共享的 axios 实例。
 */
import api from '@/shared/api/api'

/** Live2D 模型文件信息 */
export interface Live2DModelFile {
  /** 文件名 */
  filename: string
  /** 文件大小（字节） */
  size: number
  /** 文件类型（moc3, model3, physics3, texture 等） */
  file_type: string
}

/** Live2D 模型元数据响应 */
export interface Live2DModelResponse {
  /** 模型唯一标识 */
  id: string
  /** 模型名称 */
  name: string
  /** 模型名称（别名，兼容 RolesPage） */
  model_name: string
  /** 模型描述 */
  description: string
  /** 模型文件列表 */
  files: Live2DModelFile[]
  /** 创建时间（ISO 字符串） */
  created_at: string
  /** 是否有预览图 */
  has_preview: boolean
  /** 上传用户 id（null 为内置模型，兼容 RolesPage） */
  user_id: string | null
  /** 模型版本号（兼容 RolesPage） */
  version: number
  /** 纹理文件路径列表（兼容 RolesPage） */
  texture_paths: string[]
}

/** 模型列表响应 */
export interface Live2DModelListResponse {
  models: Live2DModelResponse[]
  total: number
}

/** 上传 Live2D 模型 zip 包 */
export async function uploadLive2DModel(formData: FormData): Promise<Live2DModelResponse> {
  const response = await api.post<Live2DModelResponse>('/pets/live2d/upload', formData)
  return response.data
}

/** 获取所有 Live2D 模型列表 */
export async function listLive2DModels(): Promise<Live2DModelListResponse> {
  const response = await api.get<Live2DModelListResponse>('/pets/live2d/models')
  return response.data
}

/** 删除指定 Live2D 模型 */
export async function deleteLive2DModel(modelId: string): Promise<void> {
  await api.delete(`/pets/live2d/${encodeURIComponent(modelId)}`)
}

/** 获取模型文件下载 URL */
export function getLive2DModelFileUrl(modelId: string, filename: string): string {
  return `/api/pets/live2d/${encodeURIComponent(modelId)}/files/${encodeURIComponent(filename)}`
}

/** 获取模型元数据 */
export async function getLive2DModelMeta(modelId: string): Promise<Live2DModelResponse> {
  const result = await listLive2DModels()
  const model = result.models.find(m => m.id === modelId)
  if (!model) {
    throw new Error(`Live2D 模型 ${modelId} 不存在`)
  }
  return model
}

/** 获取模型预览图 URL */
export function getLive2DModelPreviewUrl(modelId: string): string {
  return `/api/pets/live2d/${encodeURIComponent(modelId)}/preview`
}