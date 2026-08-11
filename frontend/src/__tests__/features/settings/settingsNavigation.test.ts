import { describe, expect, it } from 'vitest'
import {
  SETTINGS_SECTIONS,
  buildSettingsPath,
  resolveSettingsLocation,
} from '@/features/settings/settingsNavigation'

describe('设置分区路由', () => {
  it('固定提供八个产品级设置分区', () => {
    expect(SETTINGS_SECTIONS.map((section) => section.id)).toEqual([
      'general',
      'models',
      'ai',
      'connections',
      'data',
      'security',
      'appearance',
      'usage',
    ])
  })

  it.each([
    ['/settings/general', '', { section: 'general', view: 'general' }],
    ['/settings/models', '', { section: 'models', view: 'models' }],
    ['/settings/ai', '?view=prompts', { section: 'ai', view: 'prompts' }],
    ['/settings/connections', '?type=messaging', { section: 'connections', view: 'messaging' }],
    ['/settings/data', '?view=collection', { section: 'data', view: 'collection' }],
    ['/settings/security', '?view=permissions', { section: 'security', view: 'permissions' }],
    ['/settings/appearance', '?section=companion', { section: 'appearance', view: 'companion' }],
    ['/settings/usage', '', { section: 'usage', view: 'usage' }],
  ])('解析 %s%s', (pathname, search, expected) => {
    expect(resolveSettingsLocation(pathname, search)).toEqual(expected)
  })

  it('为连接和外观保留设计文档指定的查询键', () => {
    expect(buildSettingsPath('connections', 'messaging')).toBe('/settings/connections?type=messaging')
    expect(buildSettingsPath('appearance', 'companion')).toBe('/settings/appearance?section=companion')
    expect(buildSettingsPath('security', 'env-vars')).toBe('/settings/security?view=env-vars')
  })
})
