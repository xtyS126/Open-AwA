import { describe, expect, it } from 'vitest'
import type { ExtensionPointType, PluginManifest, SchemaValidationResult } from '../types/api'

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
