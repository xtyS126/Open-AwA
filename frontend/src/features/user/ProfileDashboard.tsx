/**
 * 用户画像仪表盘组件——替换原有的简单 AI 画像标签页，
 * 提供雷达图、置信度分布、时间线和快速操作。
 */

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  RefreshCw, Edit3, Download, Trash2, TrendingUp,
  PieChart, Clock, Activity, Loader2, Sparkles,
} from 'lucide-react'
import { shallow } from 'zustand/shallow'
import { useProfileStore } from '@/shared/store/profileStore'
import { exportProfile, purgeProfile } from '@/shared/api/profileApi'
import ProfileRadarChart from './ProfileRadarChart'
import ProfileConfidenceBar from './ProfileConfidenceBar'
import ProfileTimeline from './ProfileTimeline'
import styles from './ProfileDashboard.module.css'

function ProfileDashboard() {
  const navigate = useNavigate()
  // 使用选择器 + shallow 浅比较，避免整个 store 变化触发重渲染
  const {
    facts, factsTotal, stats, extractionLogs,
    loading, extracting, error,
    fetchFacts, fetchStats, fetchExtractionLogs,
    triggerExtraction, refreshAllFacts, clearError,
  } = useProfileStore(s => ({
    facts: s.facts,
    factsTotal: s.factsTotal,
    stats: s.stats,
    extractionLogs: s.extractionLogs,
    loading: s.loading,
    extracting: s.extracting,
    error: s.error,
    fetchFacts: s.fetchFacts,
    fetchStats: s.fetchStats,
    fetchExtractionLogs: s.fetchExtractionLogs,
    triggerExtraction: s.triggerExtraction,
    refreshAllFacts: s.refreshAllFacts,
    clearError: s.clearError,
  }), shallow)

  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    void fetchFacts()
    void fetchStats()
    void fetchExtractionLogs(10, 0)
  }, [fetchFacts, fetchStats, fetchExtractionLogs])

  const handleExtract = async () => {
    await triggerExtraction()
  }

  const handleRefresh = async () => {
    await refreshAllFacts()
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const data = await exportProfile()
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `user_profile_${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // 静默
    } finally {
      setExporting(false)
    }
  }

  const handlePurge = async () => {
    if (!confirm('确定要清空所有画像数据吗？此操作不可撤销。')) return
    try {
      await purgeProfile()
      await fetchFacts()
      await fetchStats()
    } catch {
      // 静默
    }
  }

  if (error) {
    return (
      <div className={styles['error-state']}>
        <p>加载画像失败: {error}</p>
        <button className="btn btn-secondary" onClick={clearError}>关闭</button>
        <button className="btn btn-primary" onClick={() => void fetchFacts()}>重试</button>
      </div>
    )
  }

  return (
    <div className={styles['dashboard']}>
      {/* 操作栏 */}
      <div className={styles['actions-bar']}>
        <h2>用户画像仪表盘</h2>
        <div className={styles['action-buttons']}>
          <button
            className="btn btn-primary"
            onClick={() => void handleExtract()}
            disabled={extracting}
          >
            {extracting ? (
              <><Loader2 size={14} className={styles['spin']} /> 分析中...</>
            ) : (
              <><Sparkles size={14} /> 智能提取</>
            )}
          </button>
          <button className="btn btn-secondary" onClick={() => void handleRefresh()} disabled={loading}>
            <RefreshCw size={14} /> 刷新
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => navigate('/profile/edit')}
          >
            <Edit3 size={14} /> 编辑画像
          </button>
          <button className="btn btn-secondary" onClick={() => void handleExport()} disabled={exporting}>
            <Download size={14} /> 导出
          </button>
          <button className="btn btn-danger-outline" onClick={handlePurge}>
            <Trash2 size={14} /> 清空
          </button>
        </div>
      </div>

      {/* 统计卡片 */}
      <div className={styles['stats-grid']}>
        <div className={styles['stat-card']}>
          <div className={styles['stat-icon']}><TrendingUp size={20} /></div>
          <div className={styles['stat-body']}>
            <span className={styles['stat-num']}>{stats?.completeness_pct ?? 0}%</span>
            <span className={styles['stat-label']}>画像完整度</span>
          </div>
        </div>
        <div className={styles['stat-card']}>
          <div className={styles['stat-icon']}><Activity size={20} /></div>
          <div className={styles['stat-body']}>
            <span className={styles['stat-num']}>{factsTotal}</span>
            <span className={styles['stat-label']}>总事实数</span>
          </div>
        </div>
        <div className={styles['stat-card']}>
          <div className={styles['stat-icon']}><PieChart size={20} /></div>
          <div className={styles['stat-body']}>
            <span className={styles['stat-num']}>{stats?.dimensions_filled ?? 0}/{stats?.total_dimensions ?? 8}</span>
            <span className={styles['stat-label']}>已覆盖维度</span>
          </div>
        </div>
        <div className={styles['stat-card']}>
          <div className={styles['stat-icon']}><Clock size={20} /></div>
          <div className={styles['stat-body']}>
            <span className={styles['stat-num']}>{stats?.avg_confidence ? (stats.avg_confidence * 100).toFixed(0) : 0}%</span>
            <span className={styles['stat-label']}>平均置信度</span>
          </div>
        </div>
      </div>

      {/* 图表行 */}
      <div className={styles['charts-row']}>
        <div className={styles['chart-panel']}>
          <h3>类别分布</h3>
          {stats?.category_distribution ? (
            <ProfileRadarChart data={stats.category_distribution} />
          ) : (
            <div className={styles['empty-chart']}>暂无数据</div>
          )}
        </div>
        <div className={styles['chart-panel']}>
          <h3>置信度分布</h3>
          {stats?.confidence_distribution ? (
            <ProfileConfidenceBar data={stats.confidence_distribution} />
          ) : (
            <div className={styles['empty-chart']}>暂无数据</div>
          )}
        </div>
      </div>

      {/* 快速事实预览 */}
      <div className={styles['facts-preview']}>
        <h3>
          最近事实
          {facts.length > 0 && (
            <span className={styles['facts-count']}>共 {facts.length} 条</span>
          )}
        </h3>
        {loading ? (
          <div className={styles['loading']}><Loader2 size={20} className={styles['spin']} /> 加载中...</div>
        ) : facts.length === 0 ? (
          <div className={styles['empty']}>
            <p>暂无画像数据</p>
            <p className={styles['hint']}>点击"智能提取"开始分析您的用户画像</p>
          </div>
        ) : (
          <div className={styles['facts-grid']}>
            {facts.slice(0, 12).map((fact) => (
              <div key={fact.id} className={styles['fact-chip']}>
                <span className={styles['fact-cat']}>{fact.category_label}</span>
                <span className={styles['fact-key']}>{fact.fact_key}</span>
                <span className={styles['fact-value']}>{fact.fact_value}</span>
                <span
                  className={`${styles['fact-conf']} ${
                    fact.confidence_label === '高' ? styles['conf-high'] :
                    fact.confidence_label === '中' ? styles['conf-med'] :
                    styles['conf-low']
                  }`}
                >
                  {(fact.confidence * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 提取时间线 */}
      <div className={styles['timeline-panel']}>
        <h3>画像提取历史</h3>
        {extractionLogs.length === 0 ? (
          <div className={styles['empty']}><p>暂无提取记录</p></div>
        ) : (
          <ProfileTimeline logs={extractionLogs} />
        )}
      </div>
    </div>
  )
}

export default ProfileDashboard
