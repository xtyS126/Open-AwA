import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { Navigate, useLocation, useNavigate, useParams } from '@/shared/routing'
import { renderWithRouter } from '@/shared/routing/testing'

function RouteProbe() {
  const location = useLocation()
  const navigate = useNavigate()
  const { conversationId } = useParams<{ conversationId?: string }>()

  return (
    <div>
      <output aria-label="当前路由">{`${location.pathname}${location.search}`}</output>
      <output aria-label="会话参数">{conversationId ?? 'none'}</output>
      <button type="button" onClick={() => navigate('/chat/new-session?tab=details', { replace: true })}>
        替换路由
      </button>
    </div>
  )
}

describe('路由适配层', () => {
  it('保留路径参数、查询参数和 replace 导航语义', async () => {
    renderWithRouter(<RouteProbe />, {
      initialEntry: '/chat/old-session?tab=summary',
      routePath: '/chat/$conversationId',
    })

    expect(await screen.findByLabelText('当前路由')).toHaveTextContent('/chat/old-session?tab=summary')
    expect(screen.getByLabelText('会话参数')).toHaveTextContent('old-session')

    fireEvent.click(screen.getByRole('button', { name: '替换路由' }))

    expect(await screen.findByLabelText('当前路由')).toHaveTextContent('/chat/new-session?tab=details')
    expect(screen.getByLabelText('会话参数')).toHaveTextContent('new-session')
  })

  it('声明式重定向完成后不重复解析同一目标', async () => {
    const rootRoute = createRootRoute({ component: () => <Outlet /> })
    const sourceRoute = createRoute({
      getParentRoute: () => rootRoute,
      path: '/source',
      component: () => <Navigate to="/target" replace />,
    })
    const targetRoute = createRoute({
      getParentRoute: () => rootRoute,
      path: '/target',
      component: () => <div>目标页面</div>,
    })
    const testRouter = createRouter({
      routeTree: rootRoute.addChildren([sourceRoute, targetRoute]),
      history: createMemoryHistory({ initialEntries: ['/source'] }),
    })
    let resolvedCount = 0
    const unsubscribe = testRouter.subscribe('onResolved', () => {
      resolvedCount += 1
    })

    render(<RouterProvider router={testRouter} />)

    expect(await screen.findByText('目标页面')).toBeInTheDocument()
    await new Promise((resolve) => window.setTimeout(resolve, 50))
    unsubscribe()
    expect(resolvedCount).toBeLessThanOrEqual(2)
  })
})
