import type { ReactElement, ReactNode } from 'react'
import { render } from '@testing-library/react'
import {
  Outlet,
  RouterContextProvider,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'

interface RouterTestOptions {
  initialEntry?: string
  initialEntries?: string[]
  routePath?: string
}

/**
 * 使用真实内存历史和路由匹配器渲染组件，避免测试依赖旧路由库的兼容外壳。
 */
export function renderWithRouter(
  element: ReactElement,
  options: RouterTestOptions = {},
) {
  const initialEntry = options.initialEntry ?? options.initialEntries?.[0] ?? '/'
  const routePath = options.routePath ?? '/$'
  const rootRoute = createRootRoute({
    component: () => <Outlet />,
  })
  const testRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: routePath,
    component: () => element,
  })
  const routeTree = rootRoute.addChildren([testRoute])
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [initialEntry] }),
  })
  const result = render(<RouterProvider router={router} />)

  return { ...result, router }
}

interface RouterTestProviderProps extends RouterTestOptions {
  children: ReactNode
}

/**
 * 为仍使用 JSX 包装形式的测试提供统一入口。
 */
export function RouterTestProvider({
  children,
  initialEntry,
  initialEntries,
  routePath,
}: RouterTestProviderProps) {
  const rootRoute = createRootRoute({
    component: () => <Outlet />,
  })
  const testRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: routePath ?? '/$',
    component: () => children,
  })
  const routeTree = rootRoute.addChildren([testRoute])
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({
      initialEntries: [initialEntry ?? initialEntries?.[0] ?? window.location.pathname],
    }),
  })

  return <RouterContextProvider router={router}>{children}</RouterContextProvider>
}
