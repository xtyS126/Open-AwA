/**
 * 微信多媒体消息 API 封装 — 提供多媒体消息列表查询、详情查询和发送接口。
 */
import api from '@/shared/api/api'

const BASE = '/weixin/multimedia'

/** 微信多媒体消息类型 */
export type WeixinMediaType = 'image' | 'voice' | 'file' | 'video'

/** 微信多媒体消息列表项 */
export interface WeixinMultimediaMessage {
  message_id: string
  from_user_id: string
  message_type: string
  text: string
  media_type: WeixinMediaType | ''
  media_id: string
  file_url: string
  file_name: string
  file_size: number
  duration_ms: number
  media_format: string
  timestamp: string
}

/** 微信多媒体消息详情 */
export interface WeixinMultimediaDetail {
  message_id: string
  session_id: string
  content: string
  role: string
  timestamp: string
  reasoning_content: string
  tool_events: Array<Record<string, unknown>>
}

/** 微信多媒体发送结果 */
export interface WeixinMultimediaSendResult {
  success: boolean
  media_type: WeixinMediaType
  media_id: string
  to_user: string
  file_name: string
  file_size: number
  upload_result: Record<string, unknown>
  send_result: Record<string, unknown>
}

/** 可下载的微信媒体资产 */
export interface WeixinMediaAsset {
  message_id: string
  media_type: WeixinMediaType
  media_format: string
  transcript: string
  transcript_status: 'pending' | 'processing' | 'completed' | 'failed' | string
  created_at: string
}

/** 多媒体列表查询参数 */
export interface WeixinMultimediaListParams {
  limit?: number
  media_type?: WeixinMediaType
}

/** 查询最近的多媒体消息列表 */
export async function listMultimedia(
  params?: WeixinMultimediaListParams
): Promise<WeixinMultimediaMessage[]> {
  const { data } = await api.get<WeixinMultimediaMessage[]>(`${BASE}/recent`, { params })
  return data
}

/** 获取指定多媒体消息的详情 */
export async function getMultimediaDetail(
  messageId: string
): Promise<WeixinMultimediaDetail> {
  const { data } = await api.get<WeixinMultimediaDetail>(`${BASE}/${messageId}`)
  return data
}

/** 查询服务端安全保存的微信媒体资产 */
export async function listMultimediaAssets(
  params?: WeixinMultimediaListParams
): Promise<WeixinMediaAsset[]> {
  const { data } = await api.get<WeixinMediaAsset[]>(`${BASE}/assets/recent`, { params })
  return data
}

/** 下载指定媒体资产，敏感 CDN 参数不会暴露到浏览器 */
export async function downloadMultimediaAsset(messageId: string): Promise<Blob> {
  const { data } = await api.get<Blob>(`${BASE}/assets/${encodeURIComponent(messageId)}/download`, {
    responseType: 'blob',
  })
  return data
}

/** 转写指定微信语音资产 */
export async function transcribeMultimediaAsset(messageId: string): Promise<WeixinMediaAsset> {
  const { data } = await api.post<WeixinMediaAsset>(`${BASE}/assets/${encodeURIComponent(messageId)}/transcribe`)
  return data
}

/** 发送多媒体消息（文件上传 + 发送） */
export async function sendMultimedia(
  formData: FormData,
  requestOptions?: { signal?: AbortSignal }
): Promise<WeixinMultimediaSendResult> {
  const { data } = await api.post<WeixinMultimediaSendResult>(`${BASE}/send`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    signal: requestOptions?.signal,
  })
  return data
}
