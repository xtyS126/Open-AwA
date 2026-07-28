import '@testing-library/jest-dom/vitest'
import React from 'react'
import { describe, expect, it } from 'vitest'
import { Navigate } from 'react-router-dom'
import { router } from '@/router'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'

/**
 * 路由懒加载覆盖测试（SubTask 22.2）
 *
 * 验证点：
 * 1. router/index.tsx 中所有 page 组件通过 React.lazy 包裹（静态源码扫描）
 * 2. 每个路由 element 被 withSuspense (Suspense) 包裹（运行时结构校验）
 * 3. Suspense fallback 为统一的 PageSkeleton 骨架屏
 *
 * 实现思路：
 * - 静态扫描：通过 Vite ?raw 导入源码字符串，匹配 React.lazy 调用数量
 * - 运行时校验：递归遍历 router.routes 树，校验每个 element 的 React 元素类型层级
 *   * Navigate 元素：跳过（兜底重定向）
 *   * ErrorBoundary 元素：children 应为 Suspense 元素（除 DevTestRoute 外）
 *   * Suspense 元素：children 应为 lazy 元素，fallback 应非空
 */

// React 内部符号：用于识别 lazy 元素与普通 React 元素
const REACT_ELEMENT_TYPE = Symbol.for('react.element')
const REACT_LAZY_TYPE = Symbol.for('react.lazy')

interface RouteEntry {
  /** 路由路径（'index' 表示索引路由） */
  path: string
  /** 路由 element React 元素 */
  element: React.ReactElement
}

/** 递归遍历路由树，收集所有携带 element 的路由节点 */
function collectRouteElements(routes: unknown[], result: RouteEntry[] = []): RouteEntry[] {
  for (const route of routes as Array<Record<string, unknown>>) {
    const element = route.element as React.ReactElement | undefined
    if (React.isValidElement(element)) {
      result.push({
        path: typeof route.path === 'string' ? route.path : 'index',
        element,
      })
    }
    const children = route.children as unknown[] | undefined
    if (Array.isArray(children)) {
      collectRouteElements(children, result)
    }
  }
  return result
}

function isReactElement(value: unknown): value is React.ReactElement {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as { $$typeof?: symbol }).$$typeof === REACT_ELEMENT_TYPE
  )
}

function isNavigateElement(value: unknown): boolean {
  return isReactElement(value) && (value as { type: unknown }).type === Navigate
}

function isErrorBoundaryElement(value: unknown): boolean {
  return isReactElement(value) && (value as { type: unknown }).type === ErrorBoundary
}

function isSuspenseElement(value: unknown): boolean {
  return isReactElement(value) && (value as { type: unknown }).type === React.Suspense
}

function isLazyElement(value: unknown): boolean {
  if (!isReactElement(value)) return false
  const type = (value as { type: { $$typeof?: symbol } }).type
  return typeof type === 'object' && type !== null && type.$$typeof === REACT_LAZY_TYPE
}

describe('router 懒加载覆盖', () => {
  it('router/index.tsx 中所有页面组件通过 React.lazy 包裹', async () => {
    // 通过 Vite ?raw 后缀以字符串形式导入源码
    const sourceModule = await import('@/router/index.tsx?raw')
    const source = sourceModule.default as string

    // 匹配 React.lazy( 调用次数（页面级懒加载）
    const lazyMatches = source.match(/React\.lazy\(/g) ?? []
    // 期望至少 20 个页面组件通过 React.lazy 包裹（实际 24 个）
    expect(lazyMatches.length).toBeGreaterThanOrEqual(20)
  })

  it('router 实例包含路由配置', () => {
    expect(router).toBeDefined()
    expect(router.routes).toBeInstanceOf(Array)
    expect(router.routes.length).toBeGreaterThan(0)
  })

  it('每个显式路径仅声明一次', () => {
    const routeElements = collectRouteElements(router.routes)
    const explicitPaths = routeElements
      .map(({ path }) => path)
      .filter((path) => path !== 'index' && path !== '*')

    expect(new Set(explicitPaths).size).toBe(explicitPaths.length)
  })

  it('每个页面级路由 element 为 Navigate 或 ErrorBoundary(Suspense(lazy)) 之一', () => {
    const routeElements = collectRouteElements(router.routes)
    expect(routeElements.length).toBeGreaterThan(0)

    let navigateCount = 0
    let suspenseWithLazyCount = 0
    let devTestRouteCount = 0
    let otherGuardCount = 0

    for (const { path, element } of routeElements) {
      // 情况 1：Navigate 元素（兜底重定向）
      if (isNavigateElement(element)) {
        navigateCount++
        continue
      }

      // 情况 4：守卫组件（RootGuard 等）非 ErrorBoundary，单独计数
      if (!isErrorBoundaryElement(element)) {
        otherGuardCount++
        continue
      }

      const child = (element.props as { children?: unknown }).children

      // 情况 3：/dev/test 路由的 children 是 DevTestRoute（内部再 lazy 加载 TestPage）
      if (!isSuspenseElement(child)) {
        expect(path).toBe('dev/test')
        devTestRouteCount++
        continue
      }

      // 情况 2：Suspense 包裹 lazy 元素
      const lazyChild = (child.props as { children?: unknown }).children
      expect(isLazyElement(lazyChild)).toBe(true)
      suspenseWithLazyCount++
    }

    // 至少 3 个 Navigate（/, *, plugins index）
    expect(navigateCount).toBeGreaterThanOrEqual(3)
    // 至少 20 个 Suspense + lazy 包裹的页面路由
    expect(suspenseWithLazyCount).toBeGreaterThanOrEqual(20)
    // /dev/test 路由恰好 1 个
    expect(devTestRouteCount).toBe(1)
    // 守卫组件至少 1 个（RootGuard）
    expect(otherGuardCount).toBeGreaterThanOrEqual(1)
  })

  it('所有 Suspense 元素的 fallback 均非空（PageSkeleton 骨架屏）', () => {
    const routeElements = collectRouteElements(router.routes)

    for (const { element } of routeElements) {
      if (!isErrorBoundaryElement(element)) continue

      const child = (element.props as { children?: unknown }).children
      if (!isSuspenseElement(child)) continue

      const fallback = (child.props as { fallback?: unknown }).fallback
      expect(fallback).toBeDefined()
      expect(fallback).not.toBeNull()
      // fallback 应为 React 元素（PageSkeleton）
      expect(isReactElement(fallback)).toBe(true)
    }
  })

  it('路由中引用的懒加载页面覆盖 router/index.tsx 中所有 React.lazy 调用', async () => {
    const sourceModule = await import('@/router/index.tsx?raw')
    const source = sourceModule.default as string
    const lazyMatchCount = (source.match(/React\.lazy\(/g) ?? []).length

    const routeElements = collectRouteElements(router.routes)
    // 使用 Set 去重（ChatPage、DiscussionsPage 在多个路径复用同一 lazy 对象）
    const uniqueLazyTypes = new Set<unknown>()
    for (const { element } of routeElements) {
      if (!isErrorBoundaryElement(element)) continue
      const child = (element.props as { children?: unknown }).children
      if (!isSuspenseElement(child)) continue
      const lazyChild = (child.props as { children?: unknown }).children
      if (isLazyElement(lazyChild)) {
        uniqueLazyTypes.add((lazyChild as { type: unknown }).type)
      }
    }

    // router/index.tsx 中所有 React.lazy 调用都对应到路由 element 中的唯一 lazy 类型
    expect(uniqueLazyTypes.size).toBe(lazyMatchCount)
  })
})
