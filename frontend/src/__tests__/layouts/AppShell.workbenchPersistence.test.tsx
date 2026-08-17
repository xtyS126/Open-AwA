import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { getPageTransitionKey } from '@/layouts/AppShell'

const workbenchShellCss = readFileSync(
  resolve(process.cwd(), 'src/features/workbench/WorkbenchShell.module.css'),
  'utf8',
)
const tokensCss = readFileSync(
  resolve(process.cwd(), 'src/styles/tokens.css'),
  'utf8',
)

describe('AppShell 工作台持久挂载键', () => {
  it.each([
    '/workbench/projects',
    '/workbench/editor',
    '/workbench/agents',
  ])('%s 共用 workbench 领域键', (pathname) => {
    expect(getPageTransitionKey(pathname)).toBe('workbench')
  })

  it('跨领域导航改变挂载键', () => {
    expect(getPageTransitionKey('/assistant')).toBe('assistant')
    expect(getPageTransitionKey('/library/knowledge')).toBe('library')
    expect(getPageTransitionKey('/settings/general')).toBe('/settings/general')
  })

  it('工作台父壳只消费已定义的主题令牌', () => {
    const usedTokens = [...workbenchShellCss.matchAll(/var\((--[\w-]+)/g)]
      .map((match) => match[1])
    const definedTokens = new Set(
      [...tokensCss.matchAll(/(--[\w-]+)\s*:/g)].map((match) => match[1]),
    )

    expect(usedTokens.filter((token) => !definedTokens.has(token))).toEqual([])
  })
})
