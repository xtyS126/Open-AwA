import { useCallback, useEffect, useMemo } from 'react'
import { BadgeCheck, BookOpen, History, MessagesSquare } from 'lucide-react'
import ExperiencePage from '@/features/experiences/ExperiencePage'
import MemoryPage from '@/features/memory/MemoryPage'
import { useLocation, useNavigate } from '@/shared/routing'
import LibrarySectionShell from './LibrarySectionShell'

export type KnowledgeView = 'short-term' | 'long-term' | 'experience' | 'quality'

function isKnowledgeView(value: string | null): value is KnowledgeView {
  return value === 'short-term' || value === 'long-term' || value === 'experience' || value === 'quality'
}

function buildKnowledgePath(view: KnowledgeView): string {
  return `/library/knowledge?view=${view}`
}

const KNOWLEDGE_TABS = [
  { id: 'short-term', label: '短期', icon: <MessagesSquare size={17} /> },
  { id: 'long-term', label: '长期', icon: <BookOpen size={17} /> },
  { id: 'experience', label: '经验', icon: <History size={17} /> },
  { id: 'quality', label: '质量', icon: <BadgeCheck size={17} /> },
] as const

/**
 * 将记忆、经验和质量评估收敛为资源库中的知识入口。
 */
export default function KnowledgeLibraryPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const params = useMemo(() => new URLSearchParams(location.search), [location.search])
  const rawView = params.get('view')
  const view: KnowledgeView = isKnowledgeView(rawView) ? rawView : 'long-term'
  const canonicalPath = buildKnowledgePath(view)

  useEffect(() => {
    if (location.pathname !== '/library/knowledge') return
    if (`${location.pathname}${location.search}` !== canonicalPath) {
      void navigate(canonicalPath, { replace: true })
    }
  }, [canonicalPath, location.pathname, location.search, navigate])

  const selectView = useCallback((nextView: KnowledgeView) => {
    void navigate(buildKnowledgePath(nextView))
  }, [navigate])

  const memoryView = view === 'experience' ? 'long-term' : view

  return (
    <LibrarySectionShell
      eyebrow="资源库"
      title="知识资源"
      subtitle="在短期对话、长期记忆、经验与质量评估之间切换，不再跨页面管理。"
      tabs={KNOWLEDGE_TABS}
      activeTab={view}
      onTabChange={selectView}
    >
      {view === 'experience' ? (
        <ExperiencePage hideHeader />
      ) : (
        <MemoryPage activeTab={memoryView} hideTabs embedded onTabChange={selectView} />
      )}
    </LibrarySectionShell>
  )
}
