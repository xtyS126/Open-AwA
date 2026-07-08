import React, { Suspense } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { Skeleton } from '@/shared/components/ui/Skeleton'

// P2: Sidebar 懒加载，减少主包体积
const Sidebar = React.lazy(() => import('@/shared/components/Sidebar/Sidebar'))

// App 布局壳：侧边栏 + 主内容区
// 子路由通过 Outlet 渲染，主题同步逻辑由 App.tsx 顶层统一处理
// 使用 location.pathname 作为 key 触发 CSS 动画实现页面切换淡入
export function AppShell() {
  const location = useLocation()

  return (
    <div className="app-container">
      <Suspense fallback={<div className="sidebar-skeleton" />}>
        <Sidebar />
      </Suspense>
      {/* 主内容区，skip-link 目标锚点 */}
      <main id="main-content" className="main-content">
        <Suspense fallback={<div className="loading-fallback"><Skeleton.Paragraph lines={4} /></div>}>
          {/* 使用 location.pathname 作为 key，触发 CSS 动画实现页面切换淡入 */}
          <div className="page-transition-wrapper" key={location.pathname}>
            <Outlet />
          </div>
        </Suspense>
      </main>
    </div>
  )
}
