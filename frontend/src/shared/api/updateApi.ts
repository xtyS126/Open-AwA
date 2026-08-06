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
 * download_url 是相对路径（/api/system/apk/download），需拼绝对地址供原生插件下载。
 */
export function buildDownloadUrl(downloadUrl: string): string {
  if (API_BASE_URL.startsWith('http')) {
    return `${API_BASE_URL.replace(/\/$/, '')}${downloadUrl}`
  }
  return downloadUrl
}
