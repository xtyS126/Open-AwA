import { useCallback, useEffect, useMemo } from 'react'
import { Compass, Users } from 'lucide-react'
import RoleMarketPage from '@/features/marketplace/RoleMarketPage'
import RolesPage from '@/features/roles/RolesPage'
import { useLocation, useNavigate } from '@/shared/routing'
import LibrarySectionShell from './LibrarySectionShell'

export type PersonaView = 'installed' | 'discover'

function isPersonaView(value: string | null): value is PersonaView {
  return value === 'installed' || value === 'discover'
}

function buildPersonaPath(view: PersonaView): string {
  return `/library/personas?view=${view}`
}

const PERSONA_TABS = [
  { id: 'installed', label: '已有角色', icon: <Users size={17} /> },
  { id: 'discover', label: '发现角色', icon: <Compass size={17} /> },
] as const

/**
 * 将角色管理和角色发现收敛为资源库中的单一入口。
 */
export default function PersonaLibraryPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const params = useMemo(() => new URLSearchParams(location.search), [location.search])
  const rawView = params.get('view')
  const view: PersonaView = isPersonaView(rawView) ? rawView : 'installed'
  const canonicalPath = buildPersonaPath(view)

  useEffect(() => {
    if (location.pathname !== '/library/personas') return
    if (`${location.pathname}${location.search}` !== canonicalPath) {
      void navigate(canonicalPath, { replace: true })
    }
  }, [canonicalPath, location.pathname, location.search, navigate])

  const selectView = useCallback((nextView: PersonaView) => {
    void navigate(buildPersonaPath(nextView))
  }, [navigate])

  return (
    <LibrarySectionShell
      eyebrow="资源库"
      title="角色资源"
      subtitle="创建自己的 Agent 角色，或从发现视图安装可复用角色。"
      tabs={PERSONA_TABS}
      activeTab={view}
      onTabChange={selectView}
    >
      {view === 'installed' ? <RolesPage embedded /> : <RoleMarketPage embedded />}
    </LibrarySectionShell>
  )
}
