import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'


const MINIMUM_ROUTER_VERSION = [1, 170, 18] as const

function parseVersion(version: string): number[] {
  const normalized = version.replace(/^[^0-9]*/, '').split('-')[0]
  return normalized.split('.').map((part) => Number(part))
}

function isAtLeast(version: string, minimum: readonly number[]): boolean {
  const actual = parseVersion(version)
  return minimum.every((part, index) => {
    const prefixMatches = minimum
      .slice(0, index)
      .every((prefixPart, prefixIndex) => actual[prefixIndex] === prefixPart)
    return !prefixMatches || (actual[index] ?? 0) >= part
  })
}

describe('路由依赖安全门禁', () => {
  it('使用无已知中高危漏洞的路由器并移除旧路由包', () => {
    const packageJson = JSON.parse(
      readFileSync(resolve(process.cwd(), 'package.json'), 'utf8'),
    ) as { dependencies: Record<string, string> }
    const packageLock = JSON.parse(
      readFileSync(resolve(process.cwd(), 'package-lock.json'), 'utf8'),
    ) as { packages: Record<string, { version?: string }> }

    const declaredVersion = packageJson.dependencies['@tanstack/react-router']
    const resolvedVersion = packageLock.packages['node_modules/@tanstack/react-router']?.version

    expect(declaredVersion).toBeDefined()
    expect(resolvedVersion).toBeDefined()
    expect(isAtLeast(declaredVersion, MINIMUM_ROUTER_VERSION)).toBe(true)
    expect(isAtLeast(resolvedVersion!, MINIMUM_ROUTER_VERSION)).toBe(true)
    expect(packageJson.dependencies['react-router-dom']).toBeUndefined()
    expect(packageJson.dependencies['react-router']).toBeUndefined()
    expect(packageLock.packages['node_modules/react-router-dom']).toBeUndefined()
    expect(packageLock.packages['node_modules/react-router']).toBeUndefined()
  })
})
