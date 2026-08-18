import { useCallback, useEffect, useRef, useState } from 'react'
import { appLogger } from '@/shared/utils/logger'
import { isNativeApp, isDesktop, getDesktopApi } from '@/shared/utils/platform'
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
  /** 桌面端：下载完成后触发安装重启 */
  install: () => Promise<void>
  reset: () => void
}

/** electron-updater 状态 → 前端 UpdateStatus 映射 */
function mapElectronStatus(
  status: string,
  data?: Record<string, unknown>,
): { status: UpdateStatus; errors?: string } {
  switch (status) {
    case 'checking':
      return { status: 'checking' }
    case 'available':
      return { status: 'available' }
    case 'not-available':
      return { status: 'idle' }
    case 'downloading':
      return { status: 'downloading' }
    case 'downloaded':
      return { status: 'idle' }
    case 'error':
      return {
        status: 'error',
        errors: typeof data?.message === 'string' ? data.message : '更新出错',
      }
    default:
      return { status: 'idle' }
  }
}

/**
 * APP 更新状态机：支持 Electron 桌面端 IPC 更新 + Android 原生容器 OTA 更新。
 * Web 端 check 为空操作。
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
  const desktopListenerRef = useRef<(() => void) | null>(null)
  dismissedRef.current = dismissed

  const check = useCallback(async () => {
    // ===== Electron 桌面端 =====
    if (isDesktop()) {
      if (checkingRef.current) return
      checkingRef.current = true
      setStatus('checking')
      try {
        await getDesktopApi()?.ipc.invoke('update:check')
        // 状态变更由 update:status-changed 监听器处理
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e)
        appLogger.error({
          event: 'desktop_update_check_failed',
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
      return
    }

    // ===== Android 原生容器：OTA 更新 =====
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
    // ===== Electron 桌面端 =====
    if (isDesktop()) {
      setStatus('downloading')
      try {
        await getDesktopApi()?.ipc.invoke('update:download')
        // 下载进度和结果由 update:status-changed 监听器处理
      } catch (e) {
        setStatus('error')
        setError(e instanceof Error ? e.message : String(e))
      }
      return
    }

    // ===== Android 原生容器：OTA 下载 =====
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

  /** 桌面端：下载完成后触发安装重启，Android 端无独立安装步骤 */
  const install = useCallback(async () => {
    if (!isDesktop()) return
    try {
      await getDesktopApi()?.ipc.invoke('update:install-and-restart')
    } catch (e) {
      setStatus('error')
      setError(e instanceof Error ? e.message : String(e))
    }
  }, [])

  // ===== Android 原生容器：下载进度订阅 =====
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

  // ===== Electron 桌面端：监听主进程更新状态变化 =====
  useEffect(() => {
    if (!isDesktop()) return

    const unsubscribe = getDesktopApi()?.ipc.on(
      'update:status-changed',
      (...args: unknown[]) => {
        const electronStatus = typeof args[0] === 'string' ? args[0] : ''
        const data = (typeof args[1] === 'object' && args[1] !== null ? args[1] : {}) as Record<string, unknown>
        const mapped = mapElectronStatus(electronStatus, data)

        if (electronStatus === 'available') {
          // 构造 UpdateInfo：桌面端主进程传递版本号和变更日志等
          setUpdateInfo({
            has_update: true,
            latest_version: typeof data?.version === 'string' ? data.version : '',
            latest_version_code: 0,
            apk_size: typeof data?.size === 'number' ? data.size : 0,
            apk_sha256: '',
            changelog: typeof data?.changelog === 'string' ? data.changelog : '',
            download_url: '',
            published_at: typeof data?.published_at === 'string' ? data.published_at : '',
          })
          setError('')
        }

        if (electronStatus === 'downloading') {
          setProgress({
            loaded: typeof data?.loaded === 'number' ? data.loaded : 0,
            total: typeof data?.total === 'number' ? data.total : 0,
            percent: typeof data?.percent === 'number' ? data.percent : 0,
          })
        }

        if (mapped.errors) {
          setError(mapped.errors)
        }

        setStatus(mapped.status)
      },
    )

    desktopListenerRef.current = unsubscribe ?? null

    return () => {
      desktopListenerRef.current?.()
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

  return { status, updateInfo, progress, error, dismissed, check, dismiss, startDownload, install, reset }
}