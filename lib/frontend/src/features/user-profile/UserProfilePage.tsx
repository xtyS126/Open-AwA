/**
 * 用户画像页面 —— 展示五层洋葱模型（surface/interest/role/values/core）。
 *
 * 功能：
 *   - 挂载时通过 AbortController 拉取画像，避免卸载后 setState
 *   - 每 30 秒轮询 pending 探针，组件卸载时清理定时器
 *   - 画像未建立（data === null）时展示空态引导
 *   - 每层卡片可折叠/展开，展示 description / structured_data / confidence
 *   - 探针确认/拒绝后从列表移除
 */
import { useState, useEffect, useCallback, memo } from 'react'
import { Loader2, AlertCircle, Layers, RefreshCw } from 'lucide-react'
import {
  userProfileApi,
  type OnionProfile,
  type OnionLayerData,
  type InterestProbe,
  type ProbeResponse,
} from './UserProfileApi'
import UserProfileProbe from './UserProfileProbe'
import styles from './UserProfilePage.module.css'

/** 五层画像的层级顺序与中文标签 */
const LAYER_LABELS: Array<{ key: keyof OnionProfile; label: string; hint: string }> = [
  { key: 'surface', label: '行为偏好', hint: '最近行为与偏好表达' },
  { key: 'interest', label: '兴趣偏好', hint: '喜欢 / 不喜欢 / 中性' },
  { key: 'role', label: '角色认同', hint: '自我定位与身份标签' },
  { key: 'values', label: '价值观', hint: '决策依据与优先级' },
  { key: 'core', label: '人格特征', hint: '核心人格与认知风格' },
]

/** 探针轮询间隔（毫秒） */
const PROBE_POLL_INTERVAL_MS = 30000

function UserProfilePage() {
  const [profile, setProfile] = useState<OnionProfile | null>(null)
  const [probes, setProbes] = useState<InterestProbe[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [respondingProbeId, setRespondingProbeId] = useState<number | null>(null)

  /** 拉取五层画像（带 AbortController，卸载时取消避免 setState） */
  useEffect(() => {
    const abortController = new AbortController()
    let mounted = true

    const fetchProfile = async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await userProfileApi.getProfile(abortController.signal)
        if (!mounted) return
        if (res.success) {
          setProfile(res.data)
        } else {
          setError(res.message || '获取画像失败')
        }
      } catch (e) {
        if (!mounted) return
        // AbortError 是用户主动取消，不计入错误
        if (e instanceof DOMException && e.name === 'AbortError') return
        setError('加载用户画像失败，请稍后重试')
      } finally {
        if (mounted) setLoading(false)
      }
    }

    void fetchProfile()
    return () => {
      mounted = false
      abortController.abort()
    }
  }, [])

  /** 每 30 秒轮询 pending 探针（挂载时立即拉取一次） */
  useEffect(() => {
    let mounted = true
    const abortController = new AbortController()

    const fetchProbes = async () => {
      try {
        const res = await userProfileApi.getProbes(abortController.signal)
        if (!mounted) return
        if (res.success && res.data) {
          setProbes(res.data)
        }
      } catch (e) {
        // 轮询失败静默处理，不打断用户阅读画像
        if (e instanceof DOMException && e.name === 'AbortError') return
        // 仅在开发模式记录，避免污染控制台
        if (import.meta.env.DEV) {
          console.warn('[user-profile] 探针轮询失败', e)
        }
      }
    }

    void fetchProbes()
    const timer = window.setInterval(fetchProbes, PROBE_POLL_INTERVAL_MS)
    return () => {
      mounted = false
      window.clearInterval(timer)
      abortController.abort()
    }
  }, [])

  /** 响应探针：调用后端，成功后从列表移除 */
  const handleRespond = useCallback(
    async (probeId: number, response: ProbeResponse) => {
      setRespondingProbeId(probeId)
      try {
        const res = await userProfileApi.respondToProbe(probeId, response)
        if (res.success) {
          setProbes((prev) => prev.filter((p) => p.id !== probeId))
        } else {
          setError(res.message || '探针响应失败')
        }
      } catch (e) {
        const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        setError(detail || '探针响应失败，请稍后重试')
      } finally {
        setRespondingProbeId(null)
      }
    },
    [],
  )

  /** 计算五层平均置信度 */
  const getOverallConfidence = useCallback((): number => {
    if (!profile) return 0
    const layers: OnionLayerData[] = [
      profile.surface,
      profile.interest,
      profile.role,
      profile.values,
      profile.core,
    ]
    const sum = layers.reduce((acc, l) => acc + l.confidence, 0)
    return Math.round((sum / layers.length) * 100)
  }, [profile])

  /** 手动刷新画像（用户点击重试按钮时调用） */
  const handleRetry = useCallback(() => {
    setError(null)
    setLoading(true)
    const abortController = new AbortController()
    userProfileApi
      .getProfile(abortController.signal)
      .then((res) => {
        if (res.success) {
          setProfile(res.data)
        } else {
          setError(res.message || '获取画像失败')
        }
      })
      .catch((e) => {
        if (e instanceof DOMException && e.name === 'AbortError') return
        setError('加载用户画像失败，请稍后重试')
      })
      .finally(() => setLoading(false))
    return () => abortController.abort()
  }, [])

  if (loading) {
    return (
      <div className={styles['page']}>
        <div className={styles['loading']}>
          <Loader2 size={24} className={styles['spin']} />
          <span>正在加载你的画像...</span>
        </div>
      </div>
    )
  }

  return (
    <div className={styles['page']}>
      {/* 页面标题 */}
      <header className={styles['page-header']}>
        <div>
          <h1 className={styles['page-title']}>我的画像</h1>
          <p className={styles['page-subtitle']}>
            五层洋葱模型 · AI 通过对话逐步理解的你
          </p>
        </div>
        {profile && (
          <button
            type="button"
            className={styles['refresh-btn']}
            onClick={handleRetry}
            aria-label="刷新画像"
          >
            <RefreshCw size={14} />
            刷新
          </button>
        )}
      </header>

      {/* 全局错误提示（不影响已有画像展示） */}
      {error && (
        <div className={styles['error-banner']} role="alert">
          <AlertCircle size={16} />
          <span>{error}</span>
          <button
            type="button"
            className={styles['dismiss-btn']}
            onClick={() => setError(null)}
          >
            关闭
          </button>
        </div>
      )}

      {/* 空态：画像尚未建立 */}
      {!profile && !error && (
        <EmptyState />
      )}

      {/* 空态但有错误：提供重试 */}
      {!profile && error && (
        <div className={styles['error-page']}>
          <AlertCircle size={48} />
          <p>{error}</p>
          <button type="button" className={styles['retry-btn']} onClick={handleRetry}>
            重试
          </button>
        </div>
      )}

      {/* 画像已建立：展示摘要 + 探针 + 五层卡片 */}
      {profile && (
        <>
          <div className={styles['summary-bar']}>
            <div className={styles['summary-item']}>
              <span className={styles['summary-label']}>总体置信度</span>
              <span className={styles['summary-value']}>{getOverallConfidence()}%</span>
            </div>
            <div className={styles['summary-item']}>
              <span className={styles['summary-label']}>最后更新</span>
              <span className={styles['summary-value']}>{formatDate(profile.updated_at)}</span>
            </div>
          </div>

          <UserProfileProbe
            probes={probes}
            onRespond={handleRespond}
            respondingProbeId={respondingProbeId}
          />

          <section className={styles['layers-section']}>
            <h2 className={styles['section-title']}>五层画像</h2>
            {LAYER_LABELS.map(({ key, label, hint }) => (
              <LayerCard
                key={key}
                layerKey={key}
                label={label}
                hint={hint}
                layerData={profile[key] as OnionLayerData}
              />
            ))}
          </section>
        </>
      )}
    </div>
  )
}

/* ────────────────────────────────────────────────────────────
 * 空态组件：画像尚未建立时的引导提示
 * ──────────────────────────────────────────────────────────── */
function EmptyState() {
  return (
    <div className={styles['empty-state']}>
      <div className={styles['empty-icon']}>
        <Layers size={56} strokeWidth={1.5} />
      </div>
      <h2 className={styles['empty-title']}>AI 正在通过对话了解你</h2>
      <p className={styles['empty-subtitle']}>
        随着对话累积，你的画像会逐步建立。五层洋葱模型将从行为偏好、兴趣、角色、价值观到核心人格，逐层深入地刻画独一无二的你。
      </p>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────
 * 单层画像卡片（纯展示组件，React.memo 优化）
 * ──────────────────────────────────────────────────────────── */
interface LayerCardProps {
  layerKey: string
  label: string
  hint: string
  layerData: OnionLayerData
}

function LayerCardImpl({ layerKey, label, hint, layerData }: LayerCardProps) {
  const [expanded, setExpanded] = useState(false)
  const confidencePct = Math.round(layerData.confidence * 100)
  const hasStructured =
    layerData.structured_data &&
    Object.keys(layerData.structured_data).length > 0

  return (
    <div className={styles['layer-card']}>
      <button
        type="button"
        className={styles['layer-header']}
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        aria-controls={`layer-body-${layerKey}`}
      >
        <div className={styles['layer-header-left']}>
          <span className={styles['expand-icon']} aria-hidden="true">
            {expanded ? '\u25BC' : '\u25B6'}
          </span>
          <div className={styles['layer-title-group']}>
            <span className={styles['layer-label']}>{label}</span>
            <span className={styles['layer-hint']}>{hint}</span>
          </div>
        </div>
        <div className={styles['confidence-bar']} aria-label={`置信度 ${confidencePct}%`}>
          <div className={styles['confidence-track']}>
            <div
              className={styles['confidence-fill']}
              style={{ width: `${Math.min(confidencePct, 100)}%` }}
            />
          </div>
          <span className={styles['confidence-text']}>{confidencePct}%</span>
        </div>
      </button>

      {expanded && (
        <div id={`layer-body-${layerKey}`} className={styles['layer-body']}>
          <p className={styles['layer-description']}>
            {layerData.description || '暂无描述'}
          </p>

          {hasStructured && (
            <div className={styles['structured-section']}>
              <h4 className={styles['structured-title']}>结构化数据</h4>
              <dl className={styles['structured-list']}>
                {Object.entries(layerData.structured_data).map(([k, v]) => (
                  <div key={k} className={styles['structured-row']}>
                    <dt className={styles['structured-key']}>{k}</dt>
                    <dd className={styles['structured-value']}>{formatValue(v)}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const LayerCard = memo(LayerCardImpl)

/** 将结构化数据值格式化为可展示字符串 */
function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) return value.map((item) => String(item)).join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** 格式化画像更新时间 */
function formatDate(dateStr: string): string {
  if (!dateStr) return '-'
  try {
    return new Date(dateStr).toLocaleString('zh-CN', {
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

export default UserProfilePage
