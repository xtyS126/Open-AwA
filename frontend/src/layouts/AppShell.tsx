import React, { Suspense } from 'react'
import { Outlet, useLocation } from '@/shared/routing'
import GlobalTopBar from '@/shared/components/GlobalTopBar/GlobalTopBar'
import DomainLocalNav from '@/shared/components/DomainLocalNav/DomainLocalNav'
import { Skeleton } from '@/shared/components/ui/Skeleton'

// P2: Sidebar 懒加载，减少主包体积
const Sidebar = React.lazy(() => import('@/shared/components/Sidebar/Sidebar'))
// 底部 Tab Bar（移动端原生 APP 导航）：随布局壳懒加载
const MobileTabBar = React.lazy(() => import('@/shared/components/MobileTabBar/MobileTabBar'))
// 问题反馈面板懒加载，挂在顶层 Outlet 之外，路由切换不卸载
const IssueFeedbackPanel = React.lazy(() => import('@/shared/components/IssueFeedbackPanel/IssueFeedbackPanel'))

// App 布局壳：侧边栏 + 主内容区（移动端纵列：主内容 + 底部 Tab Bar）
// 子路由通过 Outlet 渲染，主题同步逻辑由 App.tsx 顶层统一处理
// 使用 location.pathname 作为 key 触发 CSS 动画实现页面切换淡入
export function AppShell() {
  const location = useLocation()

  return (
    <div className="app-container">
      <Suspense fallback={<div className="sidebar-skeleton" />}>
        <Sidebar />
      </Suspense>
      <div className="app-workspace">
        <GlobalTopBar />
        {/* 主内容区，skip-link 目标锚点 */}
        {/* a11y: tabIndex={-1} 使 #main-content 可被 skip-link 编程式聚焦 */}
        <main id="main-content" className="main-content" tabIndex={-1}>
          <DomainLocalNav />
          <Suspense fallback={<div className="loading-fallback"><Skeleton.Paragraph lines={4} /></div>}>
            {/* 使用 location.pathname 作为 key，触发 CSS 动画实现页面切换淡入 */}
            <div className="page-transition-wrapper" key={location.pathname}>
              <Outlet />
            </div>
          </Suspense>
        </main>
      </div>
      {/* 移动端底部 Tab Bar：桌面端 useBreakpoint 守卫不渲染 */}
      <Suspense fallback={null}>
        <MobileTabBar />
      </Suspense>
      {/* 全局问题反馈面板：挂在 Outlet 之外，跨路由持久 */}
      <Suspense fallback={null}>
        <IssueFeedbackPanel />
      </Suspense>
    </div>
  )
}
