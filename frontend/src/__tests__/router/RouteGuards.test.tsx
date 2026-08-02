import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { RootGuard } from '@/router/RouteGuards'
import { useAuthStore } from '@/shared/store/authStore'

describe('RootGuard 路由收敛', () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: null,
      apiKey: null,
      isAuthenticated: false,
      isInitialized: true,
      isSystemInitialized: true,
    })
  })

  it('未登录访问根路径时只重定向到登录页', async () => {
    const rootRoute = createRootRoute({ component: RootGuard })
    const indexRoute = createRoute({
      getParentRoute: () => rootRoute,
      path: '/',
      component: () => null,
    })
    const loginRoute = createRoute({
      getParentRoute: () => rootRoute,
      path: '/login',
      component: () => <div>登录页面</div>,
    })
    const chatRoute = createRoute({
      getParentRoute: () => rootRoute,
      path: '/chat',
      component: () => <div>聊天页面</div>,
    })
    const testRouter = createRouter({
      routeTree: rootRoute.addChildren([indexRoute, loginRoute, chatRoute]),
      history: createMemoryHistory({ initialEntries: ['/'] }),
    })
    let resolvedCount = 0
    const unsubscribe = testRouter.subscribe('onResolved', () => {
      resolvedCount += 1
    })

    render(<RouterProvider router={testRouter} />)

    expect(await screen.findByText('登录页面')).toBeInTheDocument()
    await new Promise((resolve) => window.setTimeout(resolve, 50))
    unsubscribe()
    expect(testRouter.state.location.pathname).toBe('/login')
    expect(resolvedCount).toBeLessThanOrEqual(3)
  })
})
