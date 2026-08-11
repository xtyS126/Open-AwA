/**
 * 设置页面主组件，按稳定路径组织产品级分区和子视图。
 */
import { lazy, Suspense, useEffect } from 'react'
import {
  Bot,
  Coins,
  Database,
  Link2,
  Palette,
  Settings as SettingsIcon,
  ShieldCheck,
  SlidersHorizontal,
} from 'lucide-react'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import PageLayout from '@/shared/components/PageLayout/PageLayout'
import { Skeleton } from '@/shared/components/ui/Skeleton'
import { useLocation, useNavigate } from '@/shared/routing'
import {
  SETTINGS_SECTIONS,
  buildSettingsPath,
  getSettingsViews,
  resolveSettingsLocation,
  type SettingsSection,
  type SettingsView,
} from './settingsNavigation'
import styles from './SettingsPage.module.css'

const GeneralTabContainer = lazy(() => import('./containers/GeneralTabContainer').then((module) => ({ default: module.GeneralTabContainer })))
const ApiTabContainer = lazy(() => import('./containers/ApiTabContainer').then((module) => ({ default: module.ApiTabContainer })))
const PromptsTabContainer = lazy(() => import('./containers/PromptsTabContainer').then((module) => ({ default: module.PromptsTabContainer })))
const BillingTabContainer = lazy(() => import('./containers/BillingTabContainer').then((module) => ({ default: module.BillingTabContainer })))
const DataRetentionTabContainer = lazy(() => import('./containers/DataRetentionTabContainer').then((module) => ({ default: module.DataRetentionTabContainer })))
const DataCollectionTabContainer = lazy(() => import('./containers/DataCollectionTabContainer').then((module) => ({ default: module.DataCollectionTabContainer })))
const AppearanceTabContainer = lazy(() => import('./containers/AppearanceTabContainer').then((module) => ({ default: module.AppearanceTabContainer })))
const BackendConnectionTabContainer = lazy(() => import('./containers/BackendConnectionTabContainer').then((module) => ({ default: module.BackendConnectionTabContainer })))
const SearchTabContainer = lazy(() => import('./containers/SearchTabContainer').then((module) => ({ default: module.SearchTabContainer })))
const ProfileSettingsTabContainer = lazy(() => import('./containers/ProfileSettingsTabContainer').then((module) => ({ default: module.ProfileSettingsTabContainer })))
const SecuritySettings = lazy(() => import('./SecuritySettings'))
const PermissionSettings = lazy(() => import('./PermissionSettings'))
const EnvVarSettings = lazy(() => import('./EnvVarSettings'))
const MCPSettings = lazy(() => import('./MCPSettings'))
const ImChannelsPage = lazy(() => import('@/features/im/ImChannelsPage'))
const PetsPage = lazy(() => import('@/features/pets/PetsPage'))

const SECTION_ICONS: Record<SettingsSection, React.ReactNode> = {
  general: <SettingsIcon size={17} />,
  models: <SlidersHorizontal size={17} />,
  ai: <Bot size={17} />,
  connections: <Link2 size={17} />,
  data: <Database size={17} />,
  security: <ShieldCheck size={17} />,
  appearance: <Palette size={17} />,
  usage: <Coins size={17} />,
}

const VIEW_LABELS: Partial<Record<SettingsView, string>> = {
  profile: '画像学习',
  search: '搜索',
  prompts: '提示词',
  backend: '后端服务器',
  messaging: '消息渠道',
  mcp: 'MCP',
  retention: '数据保留',
  collection: '数据采集',
  security: '安全策略',
  permissions: '权限',
  'env-vars': '环境变量',
  visual: '主题与布局',
  companion: '桌面伴侣',
}

function TabLoadingFallback() {
  return (
    <div className={styles['settings-loading']}>
      <Skeleton variant="rectangular" height="var(--space-10)" width="40%" />
      <Skeleton.Paragraph lines={6} />
    </div>
  )
}

function withSettingsBoundary(name: string, content: React.ReactNode) {
  return (
    <ErrorBoundary name={name}>
      <Suspense fallback={<TabLoadingFallback />}>{content}</Suspense>
    </ErrorBoundary>
  )
}

function renderSettingsContent(view: SettingsView) {
  switch (view) {
    case 'general':
      return withSettingsBoundary('GeneralSettings', <GeneralTabContainer />)
    case 'models':
      return withSettingsBoundary('ApiSettings', <ApiTabContainer />)
    case 'profile':
      return withSettingsBoundary('ProfileSettings', <ProfileSettingsTabContainer />)
    case 'search':
      return withSettingsBoundary('SearchSettings', <SearchTabContainer />)
    case 'prompts':
      return withSettingsBoundary('PromptsSettings', <PromptsTabContainer />)
    case 'backend':
      return withSettingsBoundary('BackendConnection', <BackendConnectionTabContainer />)
    case 'messaging':
      return withSettingsBoundary('MessagingConnections', <ImChannelsPage />)
    case 'mcp':
      return withSettingsBoundary('MCPSettings', <MCPSettings />)
    case 'retention':
      return withSettingsBoundary('DataRetentionSettings', <DataRetentionTabContainer />)
    case 'collection':
      return withSettingsBoundary('DataCollectionSettings', <DataCollectionTabContainer />)
    case 'security':
      return withSettingsBoundary('SecuritySettings', <SecuritySettings />)
    case 'permissions':
      return withSettingsBoundary('PermissionSettings', <PermissionSettings />)
    case 'env-vars':
      return withSettingsBoundary('EnvVarSettings', <EnvVarSettings />)
    case 'visual':
      return withSettingsBoundary('AppearanceSettings', <AppearanceTabContainer />)
    case 'companion':
      return withSettingsBoundary('CompanionSettings', <PetsPage />)
    case 'usage':
      return withSettingsBoundary('BillingSettings', <BillingTabContainer />)
    default:
      return null
  }
}

export default function SettingsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const { section, view } = resolveSettingsLocation(location.pathname, location.search)
  const canonicalPath = buildSettingsPath(section, view)
  const views = getSettingsViews(section)

  useEffect(() => {
    if (!location.pathname.startsWith('/settings/')) return
    if (`${location.pathname}${location.search}` !== canonicalPath) {
      void navigate(canonicalPath, { replace: true })
    }
  }, [canonicalPath, location.pathname, location.search, navigate])

  const selectSection = (nextSection: SettingsSection) => {
    void navigate(buildSettingsPath(nextSection))
  }

  const selectView = (nextView: SettingsView) => {
    void navigate(buildSettingsPath(section, nextView))
  }

  return (
    <PageLayout title="设置" className={styles['settings-page']}>
      <nav className={styles['tab-bar']} aria-label="设置分区">
        {SETTINGS_SECTIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`${styles['tab-item']} ${section === item.id ? styles.active : ''}`}
            aria-current={section === item.id ? 'page' : undefined}
            onClick={() => selectSection(item.id)}
          >
            {SECTION_ICONS[item.id]}
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      {views.length > 1 && (
        <div className={styles['sub-tab-bar']} role="tablist" aria-label={`${SETTINGS_SECTIONS.find((item) => item.id === section)?.label ?? '设置'}子视图`}>
          {views.map((item) => (
            <button
              key={item}
              type="button"
              role="tab"
              aria-selected={view === item}
              className={`${styles['sub-tab-item']} ${view === item ? styles['sub-active'] : ''}`}
              onClick={() => selectView(item)}
            >
              {VIEW_LABELS[item] ?? item}
            </button>
          ))}
        </div>
      )}

      <div className={styles['settings-content']}>
        {renderSettingsContent(view)}
      </div>
    </PageLayout>
  )
}
