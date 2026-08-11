import {
  navigationManifest,
  type NavigationDomain,
  type NavigationEntry,
} from './navigationManifest'

function matchesPath(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(`${prefix}/`)
}

function matchingPrefixLength(entry: NavigationEntry, pathname: string): number {
  return [...entry.matchPrefixes, ...entry.legacyPaths].reduce(
    (longest, prefix) => matchesPath(pathname, prefix)
      ? Math.max(longest, prefix.length)
      : longest,
    -1,
  )
}

export function getActiveDomain(pathname: string): NavigationDomain | undefined {
  return navigationManifest.domains.find((domain) =>
    [...domain.matchPrefixes, ...domain.legacyPaths].some((prefix) =>
      matchesPath(pathname, prefix),
    ),
  )
}

export function getActiveChild(
  domain: NavigationDomain,
  pathname: string,
): NavigationEntry | undefined {
  return domain.children.reduce<NavigationEntry | undefined>((current, entry) => {
    const entryMatchLength = matchingPrefixLength(entry, pathname)
    if (entryMatchLength < 0) return current
    if (!current) return entry
    return entryMatchLength > matchingPrefixLength(current, pathname) ? entry : current
  }, undefined)
}
