import '@testing-library/jest-dom/vitest'
import React from 'react'
import { describe, expect, it } from 'vitest'
import { Navigate } from '@/shared/routing'
import { routeDefinitions, router, workbenchRoute } from '@/router'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'

const REACT_ELEMENT_TYPE = Symbol.for('react.element')
const REACT_LAZY_TYPE = Symbol.for('react.lazy')

function isReactElement(value: unknown): value is React.ReactElement {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as { $$typeof?: symbol }).$$typeof === REACT_ELEMENT_TYPE
  )
}

function isNavigateElement(value: unknown): boolean {
  return isReactElement(value) && value.type === Navigate
}

function isErrorBoundaryElement(value: unknown): boolean {
  return isReactElement(value) && value.type === ErrorBoundary
}

function isSuspenseElement(value: unknown): boolean {
  return isReactElement(value) && value.type === React.Suspense
}

function isLazyElement(value: unknown): boolean {
  if (!isReactElement(value)) return false
  const type = value.type as { $$typeof?: symbol }
  return typeof type === 'object' && type !== null && type.$$typeof === REACT_LAZY_TYPE
}

describe('应用路由树', () => {
  it('所有页面组件均按路由懒加载', async () => {
    const sourceModule = await import('@/router/index.tsx?raw')
    const source = sourceModule.default as string
    const lazyMatches = source.match(/React\.lazy\(/g) ?? []

    expect(lazyMatches.length).toBeGreaterThanOrEqual(20)
  })

  it('创建可用的浏览器路由实例', () => {
    expect(router).toBeDefined()
    expect(router.routeTree).toBeDefined()
    expect(routeDefinitions.length).toBeGreaterThan(0)
  })

  it('每个显式路径仅声明一次', () => {
    const paths = routeDefinitions.map(({ path }) => path)

    expect(new Set(paths).size).toBe(paths.length)
  })

  it('五个工作域均有规范路由且旧入口只执行重定向', () => {
    const byPath = new Map(routeDefinitions.map(({ path, element }) => [path, element]))

    expect(byPath.has('/assistant')).toBe(true)
    expect(byPath.has('/workbench/projects')).toBe(true)
    expect(byPath.has('/automations/overview')).toBe(true)
    expect(byPath.has('/library/capabilities')).toBe(true)
    expect(byPath.has('/activity/overview')).toBe(true)

    expect(isNavigateElement(byPath.get('/chat'))).toBe(true)
    expect(isNavigateElement(byPath.get('/workspace'))).toBe(true)
    expect(isNavigateElement(byPath.get('/skills'))).toBe(true)
    expect(isNavigateElement(byPath.get('/dashboard'))).toBe(true)
  })

  it('能力资源旧入口只重定向到带查询状态的规范路由', () => {
    const byPath = new Map(routeDefinitions.map(({ path, element }) => [path, element]))

    expect((byPath.get('/skills')?.props as { to?: string }).to).toBe(
      '/library/capabilities?type=skill&view=installed',
    )
    expect((byPath.get('/skills/market')?.props as { to?: string }).to).toBe(
      '/library/capabilities?type=skill&view=discover',
    )
    expect((byPath.get('/plugins')?.props as { to?: string }).to).toBe(
      '/library/capabilities?type=plugin&view=installed',
    )
    expect((byPath.get('/plugins/manage')?.props as { to?: string }).to).toBe(
      '/library/capabilities?type=plugin&view=installed',
    )
    expect(byPath.has('/library/capabilities/plugin/$pluginId/config')).toBe(true)
  })

  it('角色、知识和画像旧入口只重定向到规范聚合页', () => {
    const byPath = new Map(routeDefinitions.map(({ path, element }) => [path, element]))

    expect((byPath.get('/roles')?.props as { to?: string }).to).toBe('/library/personas?view=installed')
    expect((byPath.get('/role-market')?.props as { to?: string }).to).toBe('/library/personas?view=discover')
    expect((byPath.get('/memory')?.props as { to?: string }).to).toBe('/library/knowledge?view=long-term')
    expect((byPath.get('/experience')?.props as { to?: string }).to).toBe('/library/knowledge?view=experience')
    expect((byPath.get('/user-profile')?.props as { to?: string }).to).toBe('/account?section=profile')
  })

  it('设置分区均有稳定路由且连接与伴侣旧入口只重定向', () => {
    const byPath = new Map(routeDefinitions.map(({ path, element }) => [path, element]))

    for (const section of ['general', 'models', 'ai', 'connections', 'data', 'security', 'appearance', 'usage']) {
      expect(byPath.has(`/settings/${section}`)).toBe(true)
    }
    expect((byPath.get('/im')?.props as { to?: string }).to).toBe('/settings/connections?type=messaging')
    expect((byPath.get('/pets')?.props as { to?: string }).to).toBe('/settings/appearance?section=companion')
  })

  it('根路径跳转仅由 RootGuard 决策', () => {
    expect(routeDefinitions.some(({ path }) => path === '/')).toBe(false)
  })

  it('每个页面路由由兼容重定向或页面错误边界承载', () => {
    let redirectCount = 0
    let suspenseWithLazyCount = 0
    let devTestRouteCount = 0

    for (const { path, element, kind } of routeDefinitions) {
      if (kind === 'redirect' || isNavigateElement(element)) {
        redirectCount += 1
        continue
      }

      expect(isErrorBoundaryElement(element)).toBe(true)
      const child = (element.props as { children?: unknown }).children

      if (!isSuspenseElement(child)) {
        expect(path).toBe('/dev/test')
        devTestRouteCount += 1
        continue
      }

      const lazyChild = (child.props as { children?: unknown }).children
      expect(isLazyElement(lazyChild)).toBe(true)
      suspenseWithLazyCount += 1
    }

    expect(redirectCount).toBeGreaterThanOrEqual(15)
    expect(suspenseWithLazyCount).toBeGreaterThanOrEqual(20)
    expect(devTestRouteCount).toBe(1)
  })

  it('所有页面加载边界都提供骨架屏', () => {
    for (const { element } of routeDefinitions) {
      if (!isErrorBoundaryElement(element)) continue

      const child = (element.props as { children?: unknown }).children
      if (!isSuspenseElement(child)) continue

      const fallback = (child.props as { fallback?: unknown }).fallback
      expect(isReactElement(fallback)).toBe(true)
    }
  })

  it('每个懒加载页面都被路由清单消费', async () => {
    const sourceModule = await import('@/router/index.tsx?raw')
    const source = sourceModule.default as string
    const lazyMatchCount = (source.match(/React\.lazy\(/g) ?? []).length
    const uniqueLazyTypes = new Set<unknown>()

    for (const { element } of routeDefinitions) {
      if (!isErrorBoundaryElement(element)) continue
      const child = (element.props as { children?: unknown }).children
      if (!isSuspenseElement(child)) continue
      const lazyChild = (child.props as { children?: unknown }).children
      if (isLazyElement(lazyChild)) {
        uniqueLazyTypes.add(lazyChild.type)
      }
    }

    const workbenchComponent = workbenchRoute.options.component as { $$typeof?: symbol }
    if (workbenchComponent?.$$typeof === REACT_LAZY_TYPE) {
      uniqueLazyTypes.add(workbenchComponent)
    }

    expect(uniqueLazyTypes.size).toBe(lazyMatchCount)
  })
})
