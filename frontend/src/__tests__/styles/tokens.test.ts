import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const tokensSource = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8')

function readScope(selector: ':root' | '.dark'): string {
  const scopeStart = tokensSource.indexOf(`${selector} {`)
  const declarationStart = tokensSource.indexOf('{', scopeStart) + 1
  const scopeEnd = tokensSource.indexOf('\n}', declarationStart)

  expect(scopeStart, `缺少 ${selector} 令牌作用域`).toBeGreaterThanOrEqual(0)
  expect(scopeEnd, `缺少 ${selector} 令牌作用域结束位置`).toBeGreaterThan(declarationStart)
  return tokensSource.slice(declarationStart, scopeEnd)
}

function readToken(scope: string, name: string): string {
  const escapedName = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const match = scope.match(new RegExp(`^\\s*${escapedName}:\\s*([^;]+);`, 'm'))

  expect(match, `缺少设计令牌 ${name}`).not.toBeNull()
  return match?.[1].trim().toLowerCase() ?? ''
}

const primaryFamily = [
  '--color-primary',
  '--color-primary-hover',
  '--color-primary-dark',
  '--color-primary-ring',
  '--color-primary-soft-bg',
  '--color-primary-softer-bg',
  '--color-primary-softest-bg',
  '--color-primary-subtle',
  '--color-primary-gradient',
  '--color-glow',
] as const

const legacyTealPattern = /#(?:0f766e|115e59|134e4a|0d9488|0891b2|06b6d4|2dd4bf|5eead4|14b8a6)|rgba?\((?:13,\s*148,\s*136|45,\s*212,\s*191)/

describe('全局设计令牌', () => {
  it.each([':root', '.dark'] as const)('%s 主操作色统一使用软晶紫罗兰', (selector) => {
    const scope = readScope(selector)

    expect(readToken(scope, '--color-primary')).toBe('#7654ff')
    expect(readToken(scope, '--color-primary-hover')).toBe('#5e3fd6')
    expect(readToken(scope, '--color-primary-dark')).toBe('#5e3fd6')
    expect(readToken(scope, '--color-primary-gradient')).toBe(
      'linear-gradient(135deg, #7654ff 0%, #a678ff 100%)',
    )

    const primaryValues = primaryFamily.map((name) => readToken(scope, name)).join(' ')
    expect(primaryValues).not.toMatch(legacyTealPattern)
  })

  it('成功、警告和错误色不随主操作色品牌化', () => {
    const root = readScope(':root')
    const dark = readScope('.dark')

    expect(readToken(root, '--color-success')).toBe('#10b981')
    expect(readToken(root, '--color-warning')).toBe('#f59e0b')
    expect(readToken(root, '--color-error')).toBe('#ef4444')
    expect(readToken(dark, '--color-success')).toBe('#34d399')
    expect(readToken(dark, '--color-warning')).toBe('#fbbf24')
    expect(readToken(dark, '--color-error')).toBe('#f87171')
  })

  it('为大型内容容器提供 2xl 圆角令牌', () => {
    expect(readToken(readScope(':root'), '--radius-2xl')).toBe('28px')
  })
})
