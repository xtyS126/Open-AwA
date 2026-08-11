import { beforeEach, describe, expect, it } from 'vitest'
import {
  getDomainEntryPath,
  readDomainHistory,
  rememberDomainPath,
} from '@/shared/navigation/domainHistory'
import { navigationManifest } from '@/shared/navigation/navigationManifest'

describe('领域最近访问路径', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('首次访问使用领域默认规范路径', () => {
    const workbench = navigationManifest.domains.find((domain) => domain.id === 'workbench')!

    expect(getDomainEntryPath(workbench, {})).toBe('/workbench/projects')
  })

  it('记录规范深链并用于下次进入同一领域', () => {
    rememberDomainPath('automations', '/automations/runs/run-1/collaboration')
    const automations = navigationManifest.domains.find((domain) => domain.id === 'automations')!
    const history = readDomainHistory()

    expect(getDomainEntryPath(automations, history)).toBe('/automations/runs/run-1/collaboration')
  })

  it('拒绝把其他领域或外部路径写入领域历史', () => {
    rememberDomainPath('library', '/settings/general')
    rememberDomainPath('assistant', 'https://example.com')

    expect(readDomainHistory()).toEqual({})
  })
})
