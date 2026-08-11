import { useCallback, useEffect, useMemo } from 'react'
import { Boxes, PackageCheck, Puzzle, Search } from 'lucide-react'
import PluginsPage from '@/features/plugins/PluginsPage'
import SkillMarketPage from '@/features/skills/SkillMarketPage'
import SkillsPage from '@/features/skills/SkillsPage'
import { useLocation, useNavigate } from '@/shared/routing'
import styles from './CapabilityLibraryPage.module.css'

export type CapabilityType = 'skill' | 'plugin'
export type CapabilityView = 'installed' | 'discover'

const DEFAULT_TYPE: CapabilityType = 'skill'
const DEFAULT_VIEW: CapabilityView = 'installed'

function isCapabilityType(value: string | null): value is CapabilityType {
  return value === 'skill' || value === 'plugin'
}

function isCapabilityView(value: string | null): value is CapabilityView {
  return value === 'installed' || value === 'discover'
}

function buildCapabilityPath(type: CapabilityType, view: CapabilityView): string {
  return `/library/capabilities?type=${type}&view=${view}`
}

/**
 * 将技能和插件的管理、发现入口收敛到同一能力资源页面。
 */
export default function CapabilityLibraryPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const params = useMemo(() => new URLSearchParams(location.search), [location.search])
  const rawType = params.get('type')
  const rawView = params.get('view')
  const type = isCapabilityType(rawType) ? rawType : DEFAULT_TYPE
  const view = isCapabilityView(rawView) ? rawView : DEFAULT_VIEW
  const canonicalPath = buildCapabilityPath(type, view)

  useEffect(() => {
    if (location.pathname !== '/library/capabilities') return
    if (`${location.pathname}${location.search}` !== canonicalPath) {
      void navigate(canonicalPath, { replace: true })
    }
  }, [canonicalPath, location.pathname, location.search, navigate])

  const selectType = useCallback((nextType: CapabilityType) => {
    void navigate(buildCapabilityPath(nextType, view))
  }, [navigate, view])

  const selectView = useCallback((nextView: CapabilityView) => {
    void navigate(buildCapabilityPath(type, nextView))
  }, [navigate, type])

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headingGroup}>
          <span className={styles.eyebrow}>资源库</span>
          <h1 className={styles.title}>能力资源</h1>
          <p className={styles.subtitle}>在一个位置管理和发现 Agent 可使用的技能与插件。</p>
        </div>
        <div className={styles.headerMark} aria-hidden="true">
          <Boxes size={28} />
        </div>
      </header>

      <div className={styles.controls}>
        <div className={styles.controlGroup}>
          <span className={styles.controlLabel}>资源类型</span>
          <div className={styles.tabs} role="tablist" aria-label="能力类型">
            <button
              type="button"
              role="tab"
              aria-selected={type === 'skill'}
              className={type === 'skill' ? styles.activeTab : styles.tab}
              onClick={() => selectType('skill')}
            >
              <PackageCheck size={17} />
              技能
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={type === 'plugin'}
              className={type === 'plugin' ? styles.activeTab : styles.tab}
              onClick={() => selectType('plugin')}
            >
              <Puzzle size={17} />
              插件
            </button>
          </div>
        </div>

        <div className={styles.controlGroup}>
          <span className={styles.controlLabel}>浏览方式</span>
          <div className={styles.tabs} role="tablist" aria-label="能力视图">
            <button
              type="button"
              role="tab"
              aria-selected={view === 'installed'}
              className={view === 'installed' ? styles.activeTab : styles.tab}
              onClick={() => selectView('installed')}
            >
              <PackageCheck size={17} />
              已安装
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={view === 'discover'}
              className={view === 'discover' ? styles.activeTab : styles.tab}
              onClick={() => selectView('discover')}
            >
              <Search size={17} />
              发现
            </button>
          </div>
        </div>
      </div>

      <section className={styles.content} aria-live="polite">
        {type === 'skill' && view === 'installed' && <SkillsPage embedded />}
        {type === 'skill' && view === 'discover' && <SkillMarketPage embedded />}
        {type === 'plugin' && (
          <PluginsPage
            activeTab={view === 'installed' ? 'installed' : 'market'}
            hideTabs
            embedded
            onTabChange={(tab) => selectView(tab === 'installed' ? 'installed' : 'discover')}
          />
        )}
      </section>
    </div>
  )
}
