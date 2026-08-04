/**
 * 向量模型 API 模块（Spec memory-model-config-chain）。
 * 封装模型注册表 / 下载 / 配置端点（/api/models/vector/*）。
 */
import { api } from './client'

/** 向量模型注册表条目 */
export interface VectorModelRegistryItem {
  name: string
  kind: 'local' | 'cloud'
  label: string
  description: string
  model_type: 'embedding' | 'rerank'
  dimension: number | null
  capabilities: string[]
  downloaded: boolean
}

/** 向量模型配置 */
export interface VectorModelConfigData {
  embedding_provider: string
  embedding_model: string
  embedding_api_key: string
  embedding_api_endpoint: string
  rerank_provider: string
  rerank_model: string
  rerank_api_key: string
  rerank_api_endpoint: string
  model_download_source: string
}

/** 下载任务状态 */
export interface DownloadTaskState {
  status: 'downloading' | 'completed' | 'failed'
  progress: number
  error?: string | null
}

export const vectorModelsAPI = {
  /** 查询模型注册表（含下载状态） */
  getRegistry: () =>
    api.get<{ success: boolean; data: { models: VectorModelRegistryItem[] } }>('/models/vector/registry'),
  /** 触发模型下载 */
  downloadModel: (model: string, kind: 'embedding' | 'rerank') =>
    api.post<{ success: boolean; message: string; task: string }>('/models/vector/download', { model, kind }),
  /** 查询下载状态 */
  getDownloadStatus: () =>
    api.get<{ success: boolean; data: { tasks: Record<string, DownloadTaskState> } }>('/models/vector/download/status'),
  /** 读取当前配置 */
  getConfig: () =>
    api.get<{ success: boolean; data: VectorModelConfigData }>('/models/vector/config'),
  /** 更新配置 */
  updateConfig: (config: Partial<VectorModelConfigData>) =>
    api.put<{ success: boolean; message: string }>('/models/vector/config', config),
}
