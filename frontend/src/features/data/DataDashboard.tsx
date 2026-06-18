/**
 * 数据看板页面。
 * 展示对话数、工具调用、平均响应时间、用户反馈等统计概览，
 * 以及角色使用分布的条形图。
 */
import { useState, useEffect, useCallback } from 'react'
import { BarChart3, MessageSquare, Wrench, Activity, ThumbsUp } from 'lucide-react'
import { getDataStats } from '@/shared/api/dataApi'
import type { DataStats } from '@/shared/api/dataApi'
import styles from './DataDashboard.module.css'

export default function DataDashboard() {
  const [stats, setStats] = useState<DataStats | null>(null)
  const [loading, setLoading] = useState(true)

  const loadStats = useCallback(async () => {
    try {
      setLoading(true)
      const data = await getDataStats()
      setStats(data)
    } catch (e) {
      console.error('加载数据统计失败', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadStats() }, [loadStats])

  if (loading) {
    return <div className={styles.loading}>加载中...</div>
  }

  if (!stats) {
    return <div className={styles.error}>加载数据失败</div>
  }

  // 计算角色使用分布的最大值，用于条形图百分比
  const maxRoleCount = stats.role_usage.length > 0
    ? Math.max(...stats.role_usage.map(r => r.count))
    : 0

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>数据看板</h1>
      </div>

      {/* 统计卡片 */}
      <div className={styles.statsGrid}>
        <div className={styles.statCard}>
          <MessageSquare size={24} className={styles.statIcon} />
          <div className={styles.statInfo}>
            <span className={styles.statValue}>{stats.conversation_count}</span>
            <span className={styles.statLabel}>对话数</span>
          </div>
        </div>
        <div className={styles.statCard}>
          <Wrench size={24} className={styles.statIcon} />
          <div className={styles.statInfo}>
            <span className={styles.statValue}>{stats.tool_call_count}</span>
            <span className={styles.statLabel}>工具调用</span>
          </div>
        </div>
        <div className={styles.statCard}>
          <Activity size={24} className={styles.statIcon} />
          <div className={styles.statInfo}>
            <span className={styles.statValue}>{stats.avg_response_time_ms.toFixed(0)}ms</span>
            <span className={styles.statLabel}>平均响应时间</span>
          </div>
        </div>
        <div className={styles.statCard}>
          <ThumbsUp size={24} className={styles.statIcon} />
          <div className={styles.statInfo}>
            <span className={styles.statValue}>{stats.feedback_count}</span>
            <span className={styles.statLabel}>用户反馈</span>
          </div>
        </div>
      </div>

      {/* 角色使用分布 */}
      {stats.role_usage.length > 0 && (
        <section className={styles.section}>
          <h2 className={styles.sectionTitle}>
            <BarChart3 size={18} />
            角色使用分布
          </h2>
          <div className={styles.roleUsageList}>
            {stats.role_usage.map(item => (
              <div key={item.role_id} className={styles.roleUsageItem}>
                <span className={styles.roleName}>{item.role_id || '默认'}</span>
                <div className={styles.roleBar}>
                  <div
                    className={styles.roleBarFill}
                    style={{
                      width: maxRoleCount > 0
                        ? `${Math.min(100, (item.count / maxRoleCount) * 100)}%`
                        : '0%',
                    }}
                  />
                </div>
                <span className={styles.roleCount}>{item.count}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
