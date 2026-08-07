import { useCallback, useEffect, useRef, useState } from 'react'
import { appLogger } from '@/shared/utils/logger'
import { isNativeApp } from '@/shared/utils/platform'
import { checkForUpdate, buildDownloadUrl, type UpdateInfo } from '@/shared/api/updateApi'
import { appUpdatePlugin } from '@/shared/api/appUpdatePlugin'

export type UpdateStatus = 'idle' | 'checking' | 'available' | 'downloading' | 'installing' | 'error'

export interface UpdateProgress {
  loaded: number
  total: number
  percent: number
}

interface AppUpdateState {
  status: UpdateStatus
  updateInfo: UpdateInfo | null
  progress: UpdateProgress | null
  error: string
  /** 用户已选择稍后（本次会话不再自动弹窗） */
  dismissed: boolean
  check: () => Promise<void>
  dismiss: () => void
  startDownload: () => Promise<void>
  reset: () => void
}

/**
 * APP 局域网 OTA 更新状态机：检查 → 提示 → 用户选择 → 下载 → 安装。
 * 仅原生容器（isNativeApp）生效；Web 端 check 为空操作。
 */
export function useAppUpdate(): AppUpdateState {
  const [status, setStatus] = useState<UpdateStatus>('idle')
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null)
  const [progress, setProgress] = useState<UpdateProgress | null>(null)
  const [error, setError] = useState('')
  const [dismissed, setDismissed] = useState(false)
  const listenerRef = useRef<{ remove: () => void } | null>(null)
  const checkingRef = useRef(false)
  const dismissedRef = useRef(false)
  dismissedRef.current = dismissed

  const check = useCallback(async () => {
    if (!isNativeApp() || checkingRef.current) return
    checkingRef.current = true
    setStatus('checking')
    try {
      const { version_code } = await appUpdatePlugin.getCurrentVersionCode()
      const info = await checkForUpdate(version_code)
      if (info.has_update && !dismissedRef.current) {
        setUpdateInfo(info)
        setProgress(null)
        setError('')
        setStatus('available')
      } else {
        setStatus('idle')
      }
    } catch (e) {
      // 后端未部署更新包 / 网络异常：显式暴露 error 状态（与"无更新"区分），
      // 由设置页展示"更新检查失败"提示，不静默降级为 idle
      const message = e instanceof Error ? e.message : String(e)
      appLogger.error({
        event: 'app_update_check_failed',
        module: 'app-update',
        action: 'check',
        status: 'failure',
        message,
      })
      setError(`更新检查失败：${message}`)
      setStatus('error')
    } finally {
      checkingRef.current = false
    }
  }, [])

  const startDownload = useCallback(async () => {
    if (!updateInfo) return
    setStatus('downloading')
    setProgress({ loaded: 0, total: updateInfo.apk_size, percent: 0 })
    try {
      // APK 下载端点需认证（get_current_user）：原生插件通过 Authorization 头携带 API Key，
      // token 不入 URL 避免泄露到访问日志/浏览器历史
      const { getCachedApiKey } = await import('@/shared/api/client')
      const result = await appUpdatePlugin.downloadAndInstall({
        url: buildDownloadUrl(updateInfo.download_url),
        fileName: `openawa-${updateInfo.latest_version}.apk`,
        sha256: updateInfo.apk_sha256,
        authToken: getCachedApiKey(),
      })
      if (result.code === 'NEED_INSTALL_PERMISSION') {
        // 用户被引导到系统"安装未知应用"设置，返回后需再次点击更新
        setStatus('available')
        setError('请在系统设置中允许安装未知来源应用后再次点击更新')
        return
      }
      setStatus('installing')
    } catch (e) {
      setStatus('error')
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [updateInfo])

  // 下载进度订阅（原生插件 notifyListeners('updateProgress')）
  useEffect(() => {
    if (!isNativeApp()) return
    let active = true
    appUpdatePlugin
      .addListener('updateProgress', (p) => {
        if (active) setProgress(p)
      })
      .then((handler) => {
        listenerRef.current = handler
      })
      .catch(() => {
        // 插件不可用时忽略（Web/测试环境）
      })
    return () => {
      active = false
      listenerRef.current?.remove()
    }
  }, [])

  const dismiss = useCallback(() => {
    setDismissed(true)
    setStatus('idle')
  }, [])

  const reset = useCallback(() => {
    setDismissed(false)
    setStatus('idle')
    setUpdateInfo(null)
    setProgress(null)
    setError('')
  }, [])

  return { status, updateInfo, progress, error, dismissed, check, dismiss, startDownload, reset }
}
