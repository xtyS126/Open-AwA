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
} from 'lucide-react'
import PageLayout from '@/shared/components/PageLayout/PageLayout'
import { lazy, Suspense } from 'react'
import styles from './SettingsPage.module.css'

// 懒加载所有 Tab 容器组件
const GeneralTabContainer = lazy(() => import('./containers/GeneralTabContainer').then(m => ({ default: m.GeneralTabContainer })))
const ApiTabContainer = lazy(() => import('./containers/ApiTabContainer').then(m => ({ default: m.ApiTabContainer })))
const PromptsTabContainer = lazy(() => import('./containers/PromptsTabContainer').then(m => ({ default: m.PromptsTabContainer })))
const BillingTabContainer = lazy(() => import('./containers/BillingTabContainer').then(m => ({ default: m.BillingTabContainer })))
const ModelsTabContainer = lazy(() => import('./containers/ModelsTabContainer').then(m => ({ default: m.ModelsTabContainer })))
const DataRetentionTabContainer = lazy(() => import('./containers/DataRetentionTabContainer').then(m => ({ default: m.DataRetentionTabContainer })))
const DataCollectionTabContainer = lazy(() => import('./containers/DataCollectionTabContainer').then(m => ({ default: m.DataCollectionTabContainer })))
const SecuritySettings = lazy(() => import('./SecuritySettings'))
const PermissionSettings = lazy(() => import('./PermissionSettings'))
const EnvVarSettings = lazy(() => import('./EnvVarSettings'))
const MCPSettings = lazy(() => import('./MCPSettings'))

/** Tab 加载占位符 */
function TabLoadingFallback() {
  return <div style={{ padding: '2rem', textAlign: 'center', color: '#9ca3af' }}>加载中...</div>
}

function SettingsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const queryParams = new URLSearchParams(location.search)
  const initialTab = queryParams.get('tab') || 'general'

  const [activeTab, setActiveTab] = useState(initialTab)

  /** URL 参数同步 */
  useEffect(() => {
    const tab = queryParams.get('tab')
    if (tab === 'communication') {
      navigate('/communication', { replace: true })
      return
    }
    if (tab && tab !== activeTab) {
      setActiveTab(tab)
    } else if (!tab && activeTab !== 'general') {
      setActiveTab('general')
    }
  }, [location.search, navigate])

  /** Tab 切换处理 */
  const handleTabChange = useCallback((tab: string) => {
    setActiveTab(tab)
    if (tab === 'general') {
      navigate('/settings')
    } else {
      navigate(`/settings?tab=${tab}`)
    }
  }, [navigate])

  /** 渲染侧边栏 */
  const renderSecondarySidebar = () => {
    const tabs = [
      { id: 'general', label: '通用设置', icon: <SettingsIcon size={18} /> },
      { id: 'api', label: 'API配置', icon: <Plug size={18} /> },
      { id: 'prompts', label: '提示词', icon: <Cpu size={18} /> },
      { id: 'billing', label: '计费配置', icon: <Briefcase size={18} /> },
      { id: 'models', label: '模型管理', icon: <Cpu size={18} /> },
      { id: 'data-retention', label: '数据保留', icon: <HardDrive size={18} /> },
      { id: 'data-collection', label: '数据采集', icon: <HardDrive size={18} /> },
      { id: 'security', label: '安全审计', icon: <ShieldAlert size={18} /> },
      { id: 'mcp', label: 'MCP配置', icon: <SettingsIcon size={18} /> },
      { id: 'permissions', label: '权限管理', icon: <Key size={18} /> },
      { id: 'env-vars', label: '环境变量', icon: <Sliders size={18} /> },
    ]

    return (
      <div className={styles['secondary-nav']} role="tablist" aria-label="设置分类">
        {tabs.map(tab => (
          <button
            key={tab.id}
            className={`${styles['nav-item']} ${activeTab === tab.id ? styles['active'] : ''}`}
            onClick={() => handleTabChange(tab.id)}
            role="tab"
            aria-selected={activeTab === tab.id}
            aria-label={tab.label}
          >
            {tab.icon}
            <span>{tab.label}</span>
          </button>
        ))}
      </div>
    )
  }

  return (
    <PageLayout 
      title="设置" 
      secondarySidebar={renderSecondarySidebar()}
      className={styles['settings-page']}
    >
      <div className={styles['settings-content']}>
        {activeTab === 'general' && (
          <Suspense fallback={<TabLoadingFallback />}>
            <GeneralTabContainer />
          </Suspense>
        )}

        {activeTab === 'api' && (
          <Suspense fallback={<TabLoadingFallback />}>
            <ApiTabContainer />
          </Suspense>
        )}

        {activeTab === 'prompts' && (
          <Suspense fallback={<TabLoadingFallback />}>
            <PromptsTabContainer />
          </Suspense>
        )}

        {activeTab === 'billing' && (
          <Suspense fallback={<TabLoadingFallback />}>
            <BillingTabContainer />
          </Suspense>
        )}

        {activeTab === 'models' && (
          <Suspense fallback={<TabLoadingFallback />}>
            <ModelsTabContainer />
          </Suspense>
        )}

        {activeTab === 'data-retention' && (
          <Suspense fallback={<TabLoadingFallback />}>
            <DataRetentionTabContainer />
          </Suspense>
        )}

        {activeTab === 'data-collection' && (
          <Suspense fallback={<TabLoadingFallback />}>
            <DataCollectionTabContainer />
          </Suspense>
        )}

        {activeTab === 'security' && (
          <div className={styles['settings-section']}>
            <h2>安全审计</h2>
            <Suspense fallback={<TabLoadingFallback />}>
              <SecuritySettings />
            </Suspense>
          </div>
        )}

        {activeTab === 'mcp' && (
          <div className={styles['settings-section']}>
            <Suspense fallback={<TabLoadingFallback />}>
              <MCPSettings />
            </Suspense>
          </div>
        )}

        {activeTab === 'permissions' && (
          <div className={styles['settings-section']}>
            <Suspense fallback={<TabLoadingFallback />}>
              <PermissionSettings />
            </Suspense>
          </div>
        )}

        {activeTab === 'env-vars' && (
          <div className={styles['settings-section']}>
            <Suspense fallback={<TabLoadingFallback />}>
              <EnvVarSettings />
            </Suspense>
          </div>
        )}
      </div>
    </PageLayout>
  )
}

export default SettingsPage
