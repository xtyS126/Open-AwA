import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const webViewStyles = [
  'src/features/account/AccountPage.module.css',
  'src/features/library/LibrarySectionShell.module.css',
  'src/features/library/CapabilityLibraryPage.module.css',
] as const

describe('Android WebView 样式兼容性', () => {
  it.each(webViewStyles)('%s 不使用 WebView 不支持的 color-mix()', (relativePath) => {
    const source = readFileSync(resolve(process.cwd(), relativePath), 'utf8')

    expect(source).not.toMatch(/color-mix\s*\(/i)
  })
})
