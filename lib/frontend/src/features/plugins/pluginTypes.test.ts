import { describe, expect, it } from 'vitest'
import type { ExtensionPointType, PluginManifest, SchemaValidationResult } from '@/shared/types/api'
import type { Plugin } from '@/features/dashboard/dashboard'
import { isBuiltinPlugin, isUninstallablePlugin } from '@/features/plugins/pluginTypes'

describe('plugin extension types', () => {
  it('supports all eight extension point types', () => {
    const points: ExtensionPointType[] = [
      'tool',
      'hook',
      'command',
      'route',
      'event_handler',
      'scheduler',
      'middleware',
      'data_provider',
    ]

    expect(points).toHaveLength(8)
    expect(points).toContain('tool')
    expect(points).toContain('data_provider')
  })

  it('accepts manifest and validation result shape', () => {
    const manifest: PluginManifest = {
      name: 'demo-plugin',
      version: '1.0.0',
      pluginApiVersion: '1.0.0',
      extensions: [
        {
          point: 'tool',
          name: 'demo-tool',
          version: '1.0.0',
          config: { timeout: 10 },
        },
      ],
    }

    const result: SchemaValidationResult = {
      valid: true,
      errors: [],
    }

    expect(manifest.extensions[0].point).toBe('tool')
    expect(result.valid).toBe(true)
  })
})

/** 构造测试用 Plugin 对象的工厂函数 */
function makePlugin(overrides: Partial<Plugin> = {}): Plugin {
  return {
    id: 'test-plugin',
    name: 'test-plugin',
    enabled: true,
    ...overrides,
  }
}

describe('isBuiltinPlugin', () => {
  it('returns true for source=builtin', () => {
    const plugin = makePlugin({ source: 'builtin' })
    expect(isBuiltinPlugin(plugin)).toBe(true)
  })

  it('returns false for source=user', () => {
    const plugin = makePlugin({ source: 'user' })
    expect(isBuiltinPlugin(plugin)).toBe(false)
  })

  it('returns false for undefined source', () => {
    const plugin = makePlugin({ source: undefined })
    expect(isBuiltinPlugin(plugin)).toBe(false)
  })

  it('returns true for undefined source but category=builtin', () => {
    // 兼容历史数据：仅设置了 category 而未设置 source
    const plugin = makePlugin({ source: undefined, category: 'builtin' })
    expect(isBuiltinPlugin(plugin)).toBe(true)
  })

  it('returns false for empty source string', () => {
    const plugin = makePlugin({ source: '' })
    expect(isBuiltinPlugin(plugin)).toBe(false)
  })
})

describe('isUninstallablePlugin', () => {
  it('returns true for is_uninstallable=true', () => {
    const plugin = makePlugin({ is_uninstallable: true })
    expect(isUninstallablePlugin(plugin)).toBe(true)
  })

  it('returns false for is_uninstallable=false', () => {
    const plugin = makePlugin({ is_uninstallable: false })
    expect(isUninstallablePlugin(plugin)).toBe(false)
  })

  it('returns false for is_uninstallable=false even when source=builtin', () => {
    // 显式标记为可卸载时，覆盖内置判定
    const plugin = makePlugin({ source: 'builtin', is_uninstallable: false })
    expect(isUninstallablePlugin(plugin)).toBe(false)
  })

  it('falls back to builtin detection when is_uninstallable is undefined', () => {
    const builtinPlugin = makePlugin({ source: 'builtin', is_uninstallable: undefined })
    expect(isUninstallablePlugin(builtinPlugin)).toBe(true)

    const userPlugin = makePlugin({ source: 'user', is_uninstallable: undefined })
    expect(isUninstallablePlugin(userPlugin)).toBe(false)
  })

  it('falls back to builtin detection when is_uninstallable is null', () => {
    const plugin = makePlugin({ source: 'builtin', is_uninstallable: null })
    expect(isUninstallablePlugin(plugin)).toBe(true)
  })
})
