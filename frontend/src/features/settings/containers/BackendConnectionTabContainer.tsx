/**
 * 后端连接 Tab 容器组件
 * 管理桌面端/web 端的差异逻辑
 */
import { useCallback } from 'react'
import { BackendConnection } from '@/features/settings/components/BackendConnection'
import { QrCodeSection } from '@/features/settings/components/QrCodeSection'
import { useAppUpdate } from '@/shared/hooks/useAppUpdate'
import { isNativeApp, isDesktop, getDesktopApi } from '@/shared/utils/platform'
import { API_BASE_URL } from '@/shared/api/client'

/** 桌面端 IPC 测试连接返回类型 */
interface DesktopTestResult {
  ok: boolean
  latency?: number
  error?: string
}

/** 桌面端 IPC 保存返回类型 */
interface DesktopSaveResult {
  success: boolean
}

export function BackendConnectionTabContainer() {
  const desktop = getDesktopApi()
  const isDesktopEnv = isDesktop()
  // APP 局域网 OTA 更新检查（仅原生容器生效）
  const { status, check } = useAppUpdate()

  /** 桌面端通过 IPC 保存后端地址到 electron-store */
  const handleSave = useCallback(async (url: string): Promise<void> => {
    if (!desktop) {
      // Web 端：组件内已调用 setBackendUrl，无需额外处理
      return
    }
    const result = await desktop.ipc.invoke('backend:set-url', { url }) as DesktopSaveResult
    if (!result.success) {
      throw new Error('保存后端地址失败')
    }
    // 桌面端主进程会发送 backend:url-changed 事件，渲染进程监听后刷新
  }, [desktop])

  /** 桌面端通过 IPC 测试连接（主进程发起请求，避免 CORS） */
  const handleTest = useCallback(async (url: string): Promise<DesktopTestResult> => {
    if (!desktop) {
      // Web 端：组件内默认实现 testConnectionWeb
      throw new Error('Web 端应使用默认测试实现')
    }
    const result = await desktop.ipc.invoke('backend:test-connection', { url }) as DesktopTestResult
    return result
  }, [desktop])

  return (
    <div className="settings-section">
      <BackendConnection
        currentUrl={API_BASE_URL}
        isDesktop={isDesktopEnv}
        onSave={isDesktopEnv ? handleSave : undefined}
        onTest={isDesktopEnv ? handleTest : undefined}
      />
      {/* 移动端接入二维码：渲染后端地址二维码供手机 App 扫码连接 */}
      <QrCodeSection />
      {/* APP 局域网 OTA 更新检查：仅原生容器显示 */}
      {isNativeApp() && (
        <div className="check-update-row">
          <span className="check-update-label">APP 版本更新</span>
          <button
            type="button"
            className="check-update-btn"
            onClick={() => void check()}
            disabled={status === 'checking'}
          >
            {status === 'checking' ? '检查中…' : '检查更新'}
          </button>
        </div>
      )}
    </div>
  )
}
