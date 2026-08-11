import { describe, expect, it } from 'vitest'
import {
  navigationManifest,
  navigationManifestSchema,
} from '@/shared/navigation/navigationManifest'
import {
  getActiveChild,
  getActiveDomain,
} from '@/shared/navigation/navigationSelectors'

describe('导航清单', () => {
  it('通过版本化 schema 校验', () => {
    expect(navigationManifestSchema.safeParse(navigationManifest).success).toBe(true)
    expect(navigationManifest.version).toBe(2)
  })

  it('严格声明五个一级工作域', () => {
    expect(navigationManifest.domains.map((domain) => domain.id)).toEqual([
      'assistant',
      'workbench',
      'automations',
      'library',
      'activity',
    ])
  })

  it('为每个领域和二级视图显式声明平台无关的导航契约', () => {
    const entries = navigationManifest.domains.flatMap((domain) => [
      domain,
      ...domain.children,
    ])
    const contractFields = [
      'order',
      'requiredCapability',
      'featureFlag',
      'platforms',
      'minimumReadiness',
      'offlineAvailable',
      'requiresProjectContext',
      'deepLinkRule',
      'selectedStateRule',
    ]

    for (const entry of entries) {
      expect(Object.keys(entry), entry.id).toEqual(
        expect.arrayContaining(contractFields),
      )
    }
  })

  it('使用唯一且递增的稳定排序值', () => {
    const assertStableOrder = (entries: ReadonlyArray<{ order: number }>) => {
      const orders = entries.map((entry) => entry.order)

      expect(new Set(orders).size).toBe(orders.length)
      expect(orders).toEqual([...orders].sort((left, right) => left - right))
    }

    assertStableOrder(navigationManifest.domains)
    for (const domain of navigationManifest.domains) {
      assertStableOrder(domain.children)
    }
  })

  it('只声明当前已注册的 Web 投影和已落地的实体深链', () => {
    const entries = navigationManifest.domains.flatMap((domain) => [
      domain,
      ...domain.children,
    ])

    for (const entry of entries) {
      expect(entry.platforms, entry.id).toEqual(['web'])
      expect(entry.minimumReadiness, entry.id).toBe('stable')
      expect(entry.offlineAvailable, entry.id).toBe(false)
      expect(entry.featureFlag, entry.id).toBeNull()
    }

    const descendantDeepLinks = navigationManifest.domains
      .flatMap((domain) => domain.children)
      .filter((entry) => entry.deepLinkRule === 'canonicalWithDescendants')
      .map((entry) => entry.id)

    expect(descendantDeepLinks).toEqual([
      'assistant.sessions',
      'automations.runs',
      'library.capabilities',
    ])
  })

  it('声明当前权限边界、项目上下文和选择态匹配语义', () => {
    const children = navigationManifest.domains.flatMap((domain) => domain.children)
    const byId = Object.fromEntries(children.map((entry) => [entry.id, entry]))

    expect(byId['assistant.current'].requiredCapability).toBe('chat:send')
    expect(byId['assistant.sessions'].requiredCapability).toBe('chat:history')
    expect(byId['workbench.editor'].requiredCapability).toBe('coding:read')
    expect(byId['automations.flows'].requiredCapability).toBe('workflow:read')
    expect(byId['automations.executors'].requiredCapability).toBe('subagent:read')
    expect(byId['library.knowledge'].requiredCapability).toBe('memory:read')
    expect(byId['activity.usage'].requiredCapability).toBe('billing:read')

    for (const domain of navigationManifest.domains) {
      expect(domain.selectedStateRule, domain.id).toBe('prefix')
      expect(domain.requiresProjectContext, domain.id).toBe(false)
      for (const entry of domain.children) {
        expect(entry.selectedStateRule, entry.id).toBe('longestPrefix')
        expect(entry.requiresProjectContext, entry.id).toBe(false)
      }
    }
  })

  it('拒绝清单、领域或二级视图中的未知字段', () => {
    expect(navigationManifestSchema.safeParse({
      ...navigationManifest,
      unknownField: true,
    }).success).toBe(false)

    const [firstDomain, ...remainingDomains] = navigationManifest.domains
    expect(navigationManifestSchema.safeParse({
      ...navigationManifest,
      domains: [{ ...firstDomain, unknownField: true }, ...remainingDomains],
    }).success).toBe(false)

    expect(navigationManifestSchema.safeParse({
      ...navigationManifest,
      domains: [
        {
          ...firstDomain,
          children: [
            { ...firstDomain.children[0], unknownField: true },
            ...firstDomain.children.slice(1),
          ],
        },
        ...remainingDomains,
      ],
    }).success).toBe(false)
  })

  it('保证所有标识和二级规范路径全局唯一', () => {
    const entries = navigationManifest.domains.flatMap((domain) => [
      domain,
      ...domain.children,
    ])

    expect(new Set(entries.map((entry) => entry.id)).size).toBe(entries.length)
    const childPaths = navigationManifest.domains.flatMap((domain) =>
      domain.children.map((entry) => entry.canonicalPath),
    )
    expect(new Set(childPaths).size).toBe(childPaths.length)
  })

  it('按规范深链解析当前领域和最长匹配的二级视图', () => {
    const domain = getActiveDomain('/automations/runs/run-42/collaboration')

    expect(domain?.id).toBe('automations')
    expect(domain && getActiveChild(domain, '/automations/runs/run-42/collaboration')?.id)
      .toBe('automations.runs')
  })

  it('迁移期仍能把旧路径解析到唯一领域和二级视图', () => {
    const domain = getActiveDomain('/vibe-coding')

    expect(domain?.id).toBe('workbench')
    expect(domain && getActiveChild(domain, '/vibe-coding')?.id)
      .toBe('workbench.agents')
  })

  it('账户和设置不属于五个工作域', () => {
    expect(getActiveDomain('/account')).toBeUndefined()
    expect(getActiveDomain('/settings/general')).toBeUndefined()
  })
})
