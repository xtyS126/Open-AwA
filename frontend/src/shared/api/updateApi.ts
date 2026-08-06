import api from '@/shared/api/api'
import { API_BASE_URL } from '@/shared/api/client'

/** 后端 update-check 返回的更新元数据 */
export interface UpdateInfo {
  has_update: boolean
  latest_version: string
  latest_version_code: number
  apk_size: number
  apk_sha256: string
  changelog: string
  download_url: string
  published_at: string
}

/** 调用后端更新检查接口（携带客户端 versionCode） */
export async function checkForUpdate(versionCode: number): Promise<UpdateInfo> {
  const { data } = await api.get('/system/update-check', { params: { version_code: versionCode } })
  return data
}

/**
 * 构造 APK 下载绝对地址。
 * APP 模式 API_BASE_URL 为局域网地址（可能含 /api 后缀，lanDiscovery 返回"接入用 API 基址"），
 * download_url 是相对路径（/api/system/apk/download，已含 /api 前缀）。
 * API_BASE_URL 也含 /api 时直接拼接会形成 /api/api 双前缀 404，必须剥掉 download_url 的重复前缀。
 */
export function buildDownloadUrl(downloadUrl: string): string {
  if (!API_BASE_URL.startsWith('http')) {
    return downloadUrl
  }
  const base = API_BASE_URL.replace(/\/$/, '')
  if (API_BASE_URL.includes('/api') && downloadUrl.startsWith('/api/')) {
    return `${base}${downloadUrl.replace(/^\/api/, '')}`
  }
  return `${base}${downloadUrl}`
}
