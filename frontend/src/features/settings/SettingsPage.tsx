/**
 * 设置页面主组件
 * 仅负责 Tab 切换和 URL 同步，不包含任何 Tab 专属状态或 API 调用逻辑
 */
import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  Settings as SettingsIcon,
  ShieldAlert,
  Cpu,
  Briefcase,
  Plug,
  HardDrive,
  Key,
  Sliders,
  Palette,
  Wrench,
  ChevronRight,
  Server,
  Search as SearchTabIcon,
  User as UserIcon,
} from 'lucide-react'
import PageLayout from '@/shared/components/PageLayout/PageLayout'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import { Skeleton } from '@/shared/components/ui/Skeleton'
import { useI18nStore } from '@/i18n'
import { lazy, Suspense } from 'react'
import styles from './SettingsPage.module.css'

// 懒加载所有 Tab 容器组件
const GeneralTabContainer = lazy(() => import('./containers/GeneralTabContainer').then(m => ({ default: m.GeneralTabContainer })))
const ApiTabContainer = lazy(() => import('./containers/ApiTabContainer').then(m => ({ default: m.ApiTabContainer })))
const PromptsTabContainer = lazy(() => import('./containers/PromptsTabContainer').then(m => ({ default: m.PromptsTabContainer })))
const BillingTabContainer = lazy(() => import('./containers/BillingTabContainer').then(m => ({ default: m.BillingTabContainer })))
const DataRetentionTabContainer = lazy(() => import('./containers/DataRetentionTabContainer').then(m => ({ default: m.DataRetentionTabContainer })))
const DataCollectionTabContainer = lazy(() => import('./containers/DataCollectionTabContainer').then(m => ({ default: m.DataCollectionTabContainer })))
const SecuritySettings = lazy(() => import('./SecuritySettings'))
const PermissionSettings = lazy(() => import('./PermissionSettings'))
const EnvVarSettings = lazy(() => import('./EnvVarSettings'))
const MCPSettings = lazy(() => import('./MCPSettings'))
const AppearanceTabContainer = lazy(() => import('./containers/AppearanceTabContainer').then(m => ({ default: m.AppearanceTabContainer })))
const BackendConnectionTabContainer = lazy(() => import('./containers/BackendConnectionTabContainer').then(m => ({ default: m.BackendConnectionTabContainer })))
const SearchTabContainer = lazy(() => import('./containers/SearchTabContainer').then(m => ({ default: m.SearchTabContainer })))
const ProfileSettingsTabContainer = lazy(() => import('./containers/ProfileSettingsTabContainer').then(m => ({ default: m.ProfileSettingsTabContainer })))

/** 旧 Tab ID 到新 URL 的重定向映射 */
const LEGACY_TAB_REDIRECTS: Record<string, string> = {
  models: '/settings?tab=api',
  'data-retention': '/settings?tab=advanced&sub=data-retention',
  'data-collection': '/settings?tab=advanced&sub=data-collection',
  security: '/settings?tab=advanced&sub=security',
  mcp: '/settings?tab=advanced&sub=mcp',
  permissions: '/settings?tab=advanced&sub=permissions',
  'env-vars': '/settings?tab=advanced&sub=env-vars',
}

/** 高级 Tab 的子项定义：labelKey 指向 i18n key */
const ADVANCED_SUB_ITEMS = [
  { id: 'data-retention', labelKey: 'settings.advanced.dataRetention', icon: <HardDrive size={16} /> },
  { id: 'data-collection', labelKey: 'settings.advanced.dataCollection', icon: <HardDrive size={16} /> },
  { id: 'security', labelKey: 'settings.advanced.security', icon: <ShieldAlert size={16} /> },
  { id: 'mcp', labelKey: 'settings.advanced.mcp', icon: <SettingsIcon size={16} /> },
  { id: 'permissions', labelKey: 'settings.advanced.permissions', icon: <Key size={16} /> },
  { id: 'env-vars', labelKey: 'settings.advanced.envVars', icon: <Sliders size={16} /> },
] as const

/** Tab 加载占位符：使用 Skeleton 模拟表单结构，减少布局抖动 */
function TabLoadingFallback() {
  return (
    <div style={{ padding: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <Skeleton variant="rectangular" height="var(--space-10)" width="40%" />
      <Skeleton.Paragraph lines={6} />
    </div>
  )
}

function SettingsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const t = useI18nStore(s => s.t)
  const initialParams = new URLSearchParams(location.search)
  const initialTab = initialParams.get('tab') || 'general'
  const initialSubTab = initialParams.get('sub') || ''

  const [activeTab, setActiveTab] = useState(initialTab)
  /** 高级 Tab 的当前子项 */
  const [activeSubTab, setActiveSubTab] = useState<string>(initialSubTab || ADVANCED_SUB_ITEMS[0].id)
  /** 高级 Tab 子导航是否展开 */
  const [advancedExpanded, setAdvancedExpanded] = useState(initialTab === 'advanced')

  /** URL 参数同步与旧 Tab 重定向 */
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const tab = params.get('tab')
    const sub = params.get('sub') || ''

    // 旧 Tab 重定向
    if (tab && LEGACY_TAB_REDIRECTS[tab]) {
      navigate(LEGACY_TAB_REDIRECTS[tab], { replace: true })
      return
    }

    if (tab === 'communication') {
      navigate('/communication', { replace: true })
      return
    }

    if (tab) {
      setActiveTab(tab)
      // 切换到高级 Tab 时自动展开子导航
      if (tab === 'advanced') {
        setAdvancedExpanded(true)
        setActiveSubTab(sub || ADVANCED_SUB_ITEMS[0].id)
      }
    } else {
      setActiveTab('general')
    }
  }, [location.search, navigate])

  /** Tab 切换处理 */
  const handleTabChange = useCallback((tab: string) => {
    setActiveTab(tab)
    if (tab === 'advanced') {
      setAdvancedExpanded(true)
      setActiveSubTab(ADVANCED_SUB_ITEMS[0].id)
      navigate('/settings?tab=advanced')
    } else if (tab === 'general') {
      navigate('/settings')
    } else {
      navigate(`/settings?tab=${tab}`)
    }
  }, [navigate])

  /** 高级子项切换处理 */
  const handleSubTabChange = useCallback((subId: string) => {
    setActiveSubTab(subId)
    navigate(`/settings?tab=advanced&sub=${subId}`)
  }, [navigate])

  /** 切换高级子导航展开/折叠 */
  const toggleAdvancedExpanded = useCallback(() => {
    setAdvancedExpanded(prev => !prev)
  }, [])

  /** 渲染水平标签栏（对齐 Canvas 设计参考）*/
  const renderTabBar = () => {
    const tabs = [
      { id: 'general', labelKey: 'settings.tab.general', icon: <SettingsIcon size={16} /> },
      { id: 'profile', labelKey: 'settings.tab.profile', icon: <UserIcon size={16} /> },
      { id: 'api', labelKey: 'settings.tab.api', icon: <Plug size={16} /> },
      { id: 'appearance', labelKey: 'settings.tab.appearance', icon: <Palette size={16} /> },
      { id: 'search', labelKey: 'settings.tab.search', icon: <SearchTabIcon size={16} /> },
      { id: 'prompts', labelKey: 'settings.tab.prompt', icon: <Cpu size={16} /> },
      { id: 'billing', labelKey: 'settings.tab.billing', icon: <Briefcase size={16} /> },
      { id: 'backend', labelKey: 'settings.tab.backend', icon: <Server size={16} /> },
      { id: 'advanced', labelKey: 'settings.tab.advanced', icon: <Wrench size={16} /> },
    ]

    return (
      <div className={styles['tab-bar']} role="tablist" aria-label={t('settings.pageTitle')}>
        {tabs.map(tab => {
          const label = t(tab.labelKey)
          return (
            <button
              key={tab.id}
              className={`${styles['tab-item']} ${activeTab === tab.id ? styles['active'] : ''}`}
              onClick={() => {
                if (tab.id === 'advanced') {
                  // 点击高级 Tab 时切换展开状态并激活
                  if (activeTab !== 'advanced') {
                    handleTabChange('advanced')
                  } else {
                    toggleAdvancedExpanded()
                  }
                } else {
                  handleTabChange(tab.id)
                }
              }}
              role="tab"
              aria-selected={activeTab === tab.id}
              aria-label={label}
              aria-expanded={tab.id === 'advanced' ? advancedExpanded : undefined}
            >
              {tab.icon}
              <span>{label}</span>
              {tab.id === 'advanced' && (
                <ChevronRight
                  size={14}
                  className={`${styles['chevron']} ${advancedExpanded ? styles['chevron-expanded'] : ''}`}
                />
              )}
            </button>
          )
        })}
      </div>
    )
  }

  /** 渲染高级 Tab 的子标签栏（水平排列，对齐 Canvas）*/
  const renderAdvancedSubTabBar = () => {
    if (!advancedExpanded) return null
    return (
      <div className={styles['sub-tab-bar']} role="tablist" aria-label={t('settings.tab.advanced')}>
        {ADVANCED_SUB_ITEMS.map(sub => {
          const label = t(sub.labelKey)
          return (
            <button
              key={sub.id}
              className={`${styles['sub-tab-item']} ${activeTab === 'advanced' && activeSubTab === sub.id ? styles['sub-active'] : ''}`}
              onClick={() => {
                if (activeTab !== 'advanced') {
                  setActiveTab('advanced')
                }
                handleSubTabChange(sub.id)
              }}
              role="tab"
              aria-selected={activeTab === 'advanced' && activeSubTab === sub.id}
              aria-label={label}
            >
              {sub.icon}
              <span>{label}</span>
            </button>
          )
        })}
      </div>
    )
  }

  /** 渲染高级 Tab 的内容 */
  const renderAdvancedContent = () => {
    switch (activeSubTab) {
      case 'data-retention':
        return (
          <ErrorBoundary name="DataRetentionSettings">
            <Suspense fallback={<TabLoadingFallback />}>
              <DataRetentionTabContainer />
            </Suspense>
          </ErrorBoundary>
        )
      case 'data-collection':
        return (
          <ErrorBoundary name="DataCollectionSettings">
            <Suspense fallback={<TabLoadingFallback />}>
              <DataCollectionTabContainer />
            </Suspense>
          </ErrorBoundary>
        )
      case 'security':
        return (
          <div className={styles['settings-section']}>
            <h2>{t('settings.advanced.security')}</h2>
            <ErrorBoundary name="SecuritySettings">
              <Suspense fallback={<TabLoadingFallback />}>
                <SecuritySettings />
              </Suspense>
            </ErrorBoundary>
          </div>
        )
      case 'mcp':
        return (
          <div className={styles['settings-section']}>
            <ErrorBoundary name="MCPSettings">
              <Suspense fallback={<TabLoadingFallback />}>
                <MCPSettings />
              </Suspense>
            </ErrorBoundary>
          </div>
        )
      case 'permissions':
        return (
          <div className={styles['settings-section']}>
            <ErrorBoundary name="PermissionSettings">
              <Suspense fallback={<TabLoadingFallback />}>
                <PermissionSettings />
              </Suspense>
            </ErrorBoundary>
          </div>
        )
      case 'env-vars':
        return (
          <div className={styles['settings-section']}>
            <ErrorBoundary name="EnvVarSettings">
              <Suspense fallback={<TabLoadingFallback />}>
                <EnvVarSettings />
              </Suspense>
            </ErrorBoundary>
          </div>
        )
      default:
        return null
    }
  }

  return (
    <PageLayout
      title={t('settings.pageTitle')}
      className={styles['settings-page']}
    >
      {/* 水平标签栏（对齐 Canvas 设计参考）*/}
      {renderTabBar()}

      <div className={styles['settings-content']}>
        {activeTab === 'general' && (
          <ErrorBoundary name="GeneralSettings">
            <Suspense fallback={<TabLoadingFallback />}>
              <GeneralTabContainer />
            </Suspense>
          </ErrorBoundary>
        )}

        {activeTab === 'profile' && (
          <ErrorBoundary name="ProfileSettings">
            <Suspense fallback={<TabLoadingFallback />}>
              <ProfileSettingsTabContainer />
            </Suspense>
          </ErrorBoundary>
        )}

        {activeTab === 'api' && (
          <ErrorBoundary name="ApiSettings">
            <Suspense fallback={<TabLoadingFallback />}>
              <ApiTabContainer />
            </Suspense>
          </ErrorBoundary>
        )}

        {activeTab === 'appearance' && (
          <ErrorBoundary name="AppearanceSettings">
            <Suspense fallback={<TabLoadingFallback />}>
              <AppearanceTabContainer />
            </Suspense>
          </ErrorBoundary>
        )}

        {activeTab === 'search' && (
          <ErrorBoundary name="SearchSettings">
            <Suspense fallback={<TabLoadingFallback />}>
              <SearchTabContainer />
            </Suspense>
          </ErrorBoundary>
        )}

        {activeTab === 'prompts' && (
          <ErrorBoundary name="PromptsSettings">
            <Suspense fallback={<TabLoadingFallback />}>
              <PromptsTabContainer />
            </Suspense>
          </ErrorBoundary>
        )}

        {activeTab === 'billing' && (
          <ErrorBoundary name="BillingSettings">
            <Suspense fallback={<TabLoadingFallback />}>
              <BillingTabContainer />
            </Suspense>
          </ErrorBoundary>
        )}

        {activeTab === 'backend' && (
          <ErrorBoundary name="BackendConnection">
            <Suspense fallback={<TabLoadingFallback />}>
              <BackendConnectionTabContainer />
            </Suspense>
          </ErrorBoundary>
        )}

        {activeTab === 'advanced' && (
          <>
            {/* 高级 Tab 子标签栏（水平排列）*/}
            {renderAdvancedSubTabBar()}
            {renderAdvancedContent()}
          </>
        )}
      </div>
    </PageLayout>
  )
}

export default SettingsPage
