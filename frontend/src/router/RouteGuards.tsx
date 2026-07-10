import React, { Suspense } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/shared/store/authStore'
import { Skeleton } from '@/shared/components/ui/Skeleton'
import { SkipLink } from '@/shared/components/SkipLink/SkipLink'
import { AppShell } from '@/layouts/AppShell'

// P2: Sidebar 懒加载，减少主包体积
const Sidebar = React.lazy(() => import('@/shared/components/Sidebar/Sidebar'))
// P2: TestPage 懒加载，仅在开发模式 /dev/test 路径下加载
const TestPage = React.lazy(() => import('@/features/test/TestPage'))

// 初始化未完成时的 App Shell 占位
// 侧边栏立即渲染，主内容区显示 Skeleton，避免初始化期间白屏
function InitializationShell() {
  return (
    <div className="app-container">
      <Suspense fallback={<div className="sidebar-skeleton" />}>
        <Sidebar />
      </Suspense>
      {/* a11y: tabIndex={-1} 使 #main-content 可被 skip-link 编程式聚焦 */}
      <main id="main-content" className="main-content" tabIndex={-1}>
        <div className="loading-fallback"><Skeleton.Paragraph lines={4} /></div>
      </main>
    </div>
  )
}

// 开发模式路由守卫：非开发环境下重定向到仪表盘
export function DevTestRoute() {
  if (!import.meta.env.DEV) {
    return <Navigate to="/dashboard" replace />
  }
  return <TestPage />
}

// 根路由守卫：根据 isInitialized / isAuthenticated 决定渲染内容
// - 未初始化：渲染 InitializationShell（侧边栏 + Loading 占位），避免在 isAuthenticated 默认 false 期间把所有非 /login 路径误重定向到 /login
// - 未认证：仅允许 /login，其他路径重定向到 /login
// - 已认证：访问 / 或 /login 重定向到 /chat，其他路径渲染 AppShell（含 Outlet）
export function RootGuard() {
  const isInitialized = useAuthStore((s) => s.isInitialized)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const location = useLocation()

  let content: React.ReactNode

  if (!isInitialized) {
    // 初始化未完成时显示 App Shell + 主内容区 loading 占位
    // 修复了"直接 URL 访问被重定向到 /chat"和"侧边栏点击无响应"两类问题
    content = <InitializationShell />
  } else if (!isAuthenticated) {
    // 未登录：仅 /login 可访问，其他路径重定向到 /login
    if (location.pathname !== '/login') {
      content = <Navigate to="/login" replace />
    } else {
      // a11y: 包裹 <main id="main-content" tabIndex={-1}> 提供 landmark 与 skip-link 聚焦目标
      content = (
        <main id="main-content" tabIndex={-1}>
          <Suspense fallback={<div className="loading-fallback"><Skeleton.Paragraph lines={3} /></div>}>
            <Outlet />
          </Suspense>
        </main>
      )
    }
  } else {
    // 已登录：访问 / 或 /login 时重定向到 /chat
    if (location.pathname === '/' || location.pathname === '/login') {
      content = <Navigate to="/chat" replace />
    } else {
      // 渲染 AppShell，子路由通过 Outlet 渲染
      content = <AppShell />
    }
  }

  return (
    <>
      {/* 可访问性：跳转到主内容链接 */}
      <SkipLink />
      {content}
    </>
  )
}
