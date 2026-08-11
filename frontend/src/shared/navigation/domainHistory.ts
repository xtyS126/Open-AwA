import { useEffect, useState } from 'react'
import type { Location } from '@/shared/routing'
import {
  navigationManifest,
  type NavigationDomain,
  type NavigationDomainId,
} from './navigationManifest'
import { getActiveDomain } from './navigationSelectors'

const STORAGE_KEY = 'openawa-domain-last-paths-v2'

export type DomainHistory = Partial<Record<NavigationDomainId, string>>

function isPathInsideDomain(domain: NavigationDomain, path: string): boolean {
  if (!path.startsWith('/')) return false
  const pathname = path.split(/[?#]/, 1)[0]
  return domain.matchPrefixes.some((prefix) => (
    pathname === prefix || pathname.startsWith(`${prefix}/`)
  ))
}

/**
 * 读取已校验的领域访问历史，损坏或越界数据会被忽略。
 */
export function readDomainHistory(): DomainHistory {
  if (typeof window === 'undefined') return {}
  try {
    const raw = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}') as unknown
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {}

    const result: DomainHistory = {}
    for (const domain of navigationManifest.domains) {
      const value = (raw as Record<string, unknown>)[domain.id]
      if (typeof value === 'string' && isPathInsideDomain(domain, value)) {
        result[domain.id] = value
      }
    }
    return result
  } catch {
    return {}
  }
}

/**
 * 仅记录属于指定领域的站内规范路径。
 */
export function rememberDomainPath(domainId: NavigationDomainId, path: string): DomainHistory {
  const history = readDomainHistory()
  const domain = navigationManifest.domains.find((item) => item.id === domainId)
  if (!domain || !isPathInsideDomain(domain, path)) return history

  const next = { ...history, [domainId]: path }
  if (typeof window !== 'undefined') {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
  }
  return next
}

export function getDomainEntryPath(domain: NavigationDomain, history: DomainHistory): string {
  const remembered = history[domain.id]
  return remembered && isPathInsideDomain(domain, remembered)
    ? remembered
    : domain.canonicalPath
}

/**
 * 在壳层导航组件中同步当前深链，并返回每个领域的再次进入路径。
 */
export function useDomainEntryPaths(location: Location): DomainHistory {
  const [history, setHistory] = useState<DomainHistory>(() => readDomainHistory())

  useEffect(() => {
    const domain = getActiveDomain(location.pathname)
    if (!domain) return
    const next = rememberDomainPath(domain.id, `${location.pathname}${location.search}`)
    setHistory(next)
  }, [location.pathname, location.search])

  return history
}
