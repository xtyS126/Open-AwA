import { describe, expect, it } from 'vitest'
import { routeDefinitions, workbenchChildRoutes, workbenchRoute } from '@/router'

describe('工作台真实父路由', () => {
  it('三个 L2 路由共享同一个 workbench parent', () => {
    expect(workbenchChildRoutes).toHaveLength(3)
    expect(workbenchChildRoutes.every((route) => route.parentRoute === workbenchRoute)).toBe(true)
  })

  it('规范路由定义仍保留完整路径供导航和退役门禁消费', () => {
    const paths = new Set(routeDefinitions.map((definition) => definition.path))

    expect(paths.has('/workbench/projects')).toBe(true)
    expect(paths.has('/workbench/editor')).toBe(true)
    expect(paths.has('/workbench/agents')).toBe(true)
  })
})
