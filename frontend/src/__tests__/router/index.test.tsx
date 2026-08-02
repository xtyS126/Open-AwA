import '@testing-library/jest-dom/vitest'
import React from 'react'
import { describe, expect, it } from 'vitest'
import { Navigate } from '@/shared/routing'
import { routeDefinitions, router } from '@/router'
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

  it('根路径跳转仅由 RootGuard 决策', () => {
    expect(routeDefinitions.some(({ path }) => path === '/')).toBe(false)
  })

  it('每个页面路由由重定向或页面错误边界承载', () => {
    let navigateCount = 0
    let suspenseWithLazyCount = 0
    let devTestRouteCount = 0

    for (const { path, element } of routeDefinitions) {
      if (isNavigateElement(element)) {
        navigateCount += 1
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

    expect(navigateCount).toBe(1)
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

    expect(uniqueLazyTypes.size).toBe(lazyMatchCount)
  })
})
