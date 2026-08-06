import { useEffect, useRef } from 'react'
import { RouterProvider } from '@tanstack/react-router'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import { appLogger } from '@/shared/utils/logger'
import { useAppInitialization } from '@/shared/hooks/useAppInitialization'
import { useAppUpdate } from '@/shared/hooks/useAppUpdate'
import { UpdateDialog } from '@/shared/components/UpdateDialog/UpdateDialog'
import { useAuthStore } from '@/shared/store/authStore'
import { useThemeStore } from '@/shared/store/themeStore'
import { mark } from '@/shared/perf/metrics'
import { router } from '@/router'

function App() {
  // 使用选择器精确订阅，避免整个 store 变化触发重渲染
  const isInitialized = useAuthStore((s) => s.isInitialized)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const { theme } = useThemeStore()
  const shellMarkedRef = useRef<boolean | null>(null)
  useAppInitialization()

  // APP 局域网 OTA 更新：认证完成后自动检查一次（仅原生容器生效）
  const { status, updateInfo, progress, error, check, dismiss, startDownload } = useAppUpdate()
  useEffect(() => {
    if (isAuthenticated) {
      void check()
    }
  }, [isAuthenticated, check])

  // P2: 认证状态解析后记录时间
  useEffect(() => {
    if (isInitialized) {
      mark('auth_resolved')
    }
  }, [isInitialized])

  // P2: 记录 App Shell 首次可见时间
  useEffect(() => {
    if (shellMarkedRef.current === null) {
      shellMarkedRef.current = true
      mark('app_shell_visible')
    }
  }, [])

  // 主题类名同步设置（壳层立即生效）
  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }, [theme])

  // NavigationLogger：通过 router.subscribe 监听导航事件
  // 替代原 useLocation + useEffect 方案，避免在 RouterProvider 外层使用 useLocation
  // 初始化时记录一次首屏路径，后续每次路径变化时记录 page_view
  useEffect(() => {
    let lastPath = window.location.pathname
    appLogger.info({
      event: 'page_view',
      module: 'app',
      action: 'navigate',
      status: 'success',
      message: 'page visited',
      extra: { path: lastPath },
    })

    const unsubscribe = router.subscribe('onResolved', (event) => {
      const currentPath = event.toLocation.pathname
      if (currentPath !== lastPath) {
        lastPath = currentPath
        appLogger.info({
          event: 'page_view',
          module: 'app',
          action: 'navigate',
          status: 'success',
          message: 'page visited',
          extra: { path: currentPath },
        })
      }
    })
    return unsubscribe
  }, [])

  // P0: 始终渲染 RouterProvider，由 RootGuard 内部根据认证状态决定具体内容
  // 更新弹窗挂载在 RouterProvider 外层，跨路由持久
  return (
    <ErrorBoundary name="Root">
      <RouterProvider router={router} />
      {isAuthenticated && updateInfo && (
        (status === 'available' || status === 'downloading' || status === 'installing' || status === 'error') && (
          <UpdateDialog
            info={updateInfo}
            status={status}
            progress={progress}
            error={error}
            onUpdate={() => void startDownload()}
            onLater={dismiss}
          />
        )
      )}
    </ErrorBoundary>
  )
}

export default App
