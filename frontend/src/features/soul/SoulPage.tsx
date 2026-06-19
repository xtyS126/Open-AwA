import { useState, useEffect, useCallback } from 'react'
import {
  getProfile,
  getProbes,
  respondProbe,
  type OnionProfile,
  type Probe,
  type LayerData,
} from './soulApi'
import ProfileCard from './ProfileCard'
import ProbeNotification from './ProbeNotification'
import styles from './SoulPage.module.css'

/** 五层画像的层级顺序 */
const LAYER_ORDER = ['surface', 'interest', 'role', 'values', 'core'] as const

function SoulPage() {
  const [profile, setProfile] = useState<OnionProfile | null>(null)
  const [probes, setProbes] = useState<Probe[]>([])
  const [expandedLayers, setExpandedLayers] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  /** 加载画像和探针数据 */
  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [profileRes, probesRes] = await Promise.all([
        getProfile().catch(() => null),
        getProbes().catch(() => null),
      ])

      if (profileRes) {
        setProfile(profileRes.profile)
      }
      if (probesRes) {
        setProbes(probesRes.probes.filter((p) => p.status === 'pending'))
      }
    } catch {
      setError('加载 Soul 画像数据失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  /** 切换某层画像的展开/折叠状态 */
  const toggleLayer = useCallback((layerName: string) => {
    setExpandedLayers((prev) => {
      const next = new Set(prev)
      if (next.has(layerName)) {
        next.delete(layerName)
      } else {
        next.add(layerName)
      }
      return next
    })
  }, [])

  /** 响应探针 */
  const handleProbeRespond = useCallback(
    async (probeId: number, status: 'confirmed' | 'rejected') => {
      try {
        await respondProbe(probeId, status)
        setProbes((prev) => prev.filter((p) => p.id !== probeId))
      } catch {
        setError('探针响应失败，请稍后重试')
      }
    },
    []
  )

  /** 计算总体置信度（五层平均值） */
  const getOverallConfidence = useCallback((): number => {
    if (!profile) return 0
    const layers: LayerData[] = [
      profile.surface,
      profile.interest,
      profile.role,
      profile.values,
      profile.core,
    ]
    const sum = layers.reduce((acc, layer) => acc + layer.confidence, 0)
    return Math.round((sum / layers.length) * 100)
  }, [profile])

  if (loading) {
    return (
      <div className={styles['soul-page']}>
        <div className={styles['loading']}>加载中...</div>
      </div>
    )
  }

  if (error && !profile) {
    return (
      <div className={styles['soul-page']}>
        <div className={styles['error-state']}>
          <p>{error}</p>
          <button
            className={styles['retry-btn']}
            onClick={loadData}
            type="button"
          >
            重试
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className={styles['soul-page']}>
      {/* 页面标题 */}
      <div className={styles['page-header']}>
        <h1 className={styles['page-title']}>Soul 画像</h1>
        <span className={styles['header-subtitle']}>
          五层洋葱模型 - AI 理解的你
        </span>
      </div>

      {/* 用户画像摘要 */}
      {profile && (
        <div className={styles['summary-bar']}>
          <div className={styles['summary-item']}>
            <span className={styles['summary-label']}>用户 ID</span>
            <span className={styles['summary-value']}>{profile.user_id}</span>
          </div>
          <div className={styles['summary-item']}>
            <span className={styles['summary-label']}>总体置信度</span>
            <span className={styles['summary-value']}>
              {getOverallConfidence()}%
            </span>
          </div>
          <div className={styles['summary-item']}>
            <span className={styles['summary-label']}>最后更新</span>
            <span className={styles['summary-value']}>
              {formatDate(profile.updated_at)}
            </span>
          </div>
        </div>
      )}

      {/* 全局错误提示 */}
      {error && (
        <div className={styles['error-toast']}>
          <span>{error}</span>
          <button
            className={styles['dismiss-btn']}
            onClick={() => setError(null)}
            type="button"
          >
            x
          </button>
        </div>
      )}

      {/* 待确认的兴趣探针 */}
      <ProbeNotification probes={probes} onRespond={handleProbeRespond} />

      {/* 五层画像卡片 */}
      <div className={styles['layers-section']}>
        <h2 className={styles['section-title']}>五层画像</h2>
        {profile ? (
          LAYER_ORDER.map((layerName) => {
            const layerData = profile[layerName]
            return (
              <ProfileCard
                key={layerName}
                layerName={layerName}
                layerData={layerData}
                isExpanded={expandedLayers.has(layerName)}
                onToggle={() => toggleLayer(layerName)}
              />
            )
          })
        ) : (
          <div className={styles['empty-hint']}>
            暂无画像数据，请先与 AI 进行对话以生成画像
          </div>
        )}
      </div>
    </div>
  )
}

/** 格式化日期字符串 */
function formatDate(dateStr: string): string {
  if (!dateStr) return '-'
  try {
    const date = new Date(dateStr)
    return date.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return dateStr
  }
}

export default SoulPage