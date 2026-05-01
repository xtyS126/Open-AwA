import { useState, Suspense, lazy } from 'react'
import styles from './CommunicationPage.module.css'

// Lazy load the WeChat module
const WechatConfigModule = lazy(() => import('./wechat-module'))

function CommunicationPage() {
  const [activeTab, setActiveTab] = useState<'wechat'>('wechat')

  return (
    <div className={styles['communication-page']}>
      <div className={styles['communication-header']}>
        <h1>通讯配置</h1>
      </div>
      <div className={styles['communication-layout']}>
        <div className={styles['communication-sidebar']}>
          <ul className={styles['sidebar-menu']}>
            <li 
              className={`${styles['sidebar-item']} ${activeTab === 'wechat' ? styles['active'] : ''}`}
              onClick={() => setActiveTab('wechat')}
            >
              微信
            </li>
            {/* Future modules can be added here */}
          </ul>
        </div>
        <div className={styles['communication-content']}>
          {activeTab === 'wechat' && (
            <Suspense fallback={<div className={styles['loading']}>加载模块中...</div>}>
              <WechatConfigModule />
            </Suspense>
          )}
        </div>
      </div>
    </div>
  )
}

export default CommunicationPage
