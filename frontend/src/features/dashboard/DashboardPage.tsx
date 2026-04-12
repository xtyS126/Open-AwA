import { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar } from 'recharts'
import { behaviorAPI, skillsAPI, pluginsAPI, memoryAPI } from '@/shared/api/api'
import { billingAPI } from '@/features/billing/billingApi'
import { BehaviorStats, BillingStats, Intent } from '@/features/dashboard/dashboard'
import styles from './DashboardPage.module.css'

const CHART_COLORS = {
  grid: 'var(--color-chart-grid)',
  axis: 'var(--color-chart-axis)',
  interactions: 'var(--color-chart-primary)',
  cost: 'var(--color-chart-secondary)',
  bar: 'var(--color-chart-3)'
}

/* 系统资源概览数据类型 */
interface SystemOverview {
  skillsTotal: number
  skillsEnabled: number
  pluginsTotal: number
  pluginsEnabled: number
  longTermMemories: number
}

function DashboardPage() {
  const [stats, setStats] = useState<BehaviorStats | null>(null)
  const [billingStats, setBillingStats] = useState<BillingStats | null>(null)
  const [systemOverview, setSystemOverview] = useState<SystemOverview>({
    skillsTotal: 0, skillsEnabled: 0,
    pluginsTotal: 0, pluginsEnabled: 0,
    longTermMemories: 0
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadStats()
  }, [])

  const loadStats = async () => {
    try {
      /* 并发加载所有数据源 */
      const [behaviorRes, billingRes, skillsRes, pluginsRes, memoryRes] = await Promise.all([
        behaviorAPI.getStats(7),
        billingAPI.getCostStatistics({ period: 'monthly' }).catch(() => ({ data: null })),
        skillsAPI.getAll().catch(() => ({ data: [] })),
        pluginsAPI.getAll().catch(() => ({ data: [] })),
        memoryAPI.getLongTerm().catch(() => ({ data: [] }))
      ])
      setStats(behaviorRes.data)
      setBillingStats(billingRes.data)

      /* 从真实接口汇总系统概览 */
      const skillsList = Array.isArray(skillsRes.data) ? skillsRes.data : (skillsRes.data?.skills || [])
      const pluginsList = Array.isArray(pluginsRes.data) ? pluginsRes.data : (pluginsRes.data?.plugins || [])
      const memoriesList = Array.isArray(memoryRes.data) ? memoryRes.data : (memoryRes.data?.memories || [])

      setSystemOverview({
        skillsTotal: skillsList.length,
        skillsEnabled: skillsList.filter((s: { enabled?: boolean }) => s.enabled).length,
        pluginsTotal: pluginsList.length,
        pluginsEnabled: pluginsList.filter((p: { enabled?: boolean }) => p.enabled).length,
        longTermMemories: memoriesList.length,
      })
    } catch (error) {
      setStats(null)
    } finally {
      setLoading(false)
    }
  }

  const formatCurrency = (amount: number, currency: string = 'USD') => {
    const symbol = currency === 'CNY' ? '¥' : '$'
    return `${symbol}${amount.toFixed(2)}`
  }

  /* 将模型使用数据转为柱状图数据 */
  const getModelBarData = () => {
    if (!billingStats?.by_model) return []
    return billingStats.by_model.slice(0, 6).map(m => ({
      name: m.model.length > 16 ? m.model.slice(0, 14) + '..' : m.model,
      cost: m.cost,
      requests: m.requests || 0
    }))
  }

  if (loading) {
    return <div className={styles['loading']}>加载中...</div>
  }

  return (
    <div className={styles['dashboard-page']}>
      <div className={styles['dashboard-header']}>
        <h1>仪表盘</h1>
        <span className={styles['header-subtitle']}>Open-AwA AI Agent 运行概览</span>
      </div>

      {/* 核心指标卡片 */}
      <div className={styles['stats-grid']}>
        <div className={styles['stat-card']}>
          <h3>总交互次数</h3>
          <p className={styles['stat-value']}>{stats?.total_interactions || 0}</p>
          <span className={styles['stat-subtitle']}>近7天</span>
        </div>
        <div className={styles['stat-card']}>
          <h3>工具使用次数</h3>
          <p className={styles['stat-value']}>{stats?.total_tools_used || 0}</p>
          <span className={styles['stat-subtitle']}>技能 + 插件调用</span>
        </div>
        <div className={styles['stat-card']}>
          <h3>本月成本</h3>
          <p className={styles['stat-value']}>{billingStats ? formatCurrency(billingStats.total_cost || 0, billingStats.currency) : '-'}</p>
          <span className={styles['stat-subtitle']}>API调用费用</span>
        </div>
        <div className={styles['stat-card']}>
          <h3>平均响应时间</h3>
          <p className={styles['stat-value']}>{stats?.average_response_time || 0}s</p>
          <span className={styles['stat-subtitle']}>端到端延迟</span>
        </div>
      </div>

      {/* 系统资源概览 */}
      <div className={styles['resource-grid']}>
        <div className={styles['resource-card']}>
          <div className={styles['resource-icon']}>S</div>
          <div className={styles['resource-info']}>
            <span className={styles['resource-title']}>技能</span>
            <span className={styles['resource-value']}>{systemOverview.skillsEnabled} / {systemOverview.skillsTotal}</span>
            <span className={styles['resource-label']}>已启用 / 总数</span>
          </div>
        </div>
        <div className={styles['resource-card']}>
          <div className={styles['resource-icon']}>P</div>
          <div className={styles['resource-info']}>
            <span className={styles['resource-title']}>插件</span>
            <span className={styles['resource-value']}>{systemOverview.pluginsEnabled} / {systemOverview.pluginsTotal}</span>
            <span className={styles['resource-label']}>已启用 / 总数</span>
          </div>
        </div>
        <div className={styles['resource-card']}>
          <div className={styles['resource-icon']}>M</div>
          <div className={styles['resource-info']}>
            <span className={styles['resource-title']}>长期记忆</span>
            <span className={styles['resource-value']}>{systemOverview.longTermMemories}</span>
            <span className={styles['resource-label']}>已存储条目</span>
          </div>
        </div>
      </div>

      {/* 图表区域 */}
      <div className={styles['charts-grid']}>
        <div className={styles['chart-card']}>
          <h3>近7天交互趋势</h3>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={stats?.chart_data || []}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
              <XAxis dataKey="day" stroke={CHART_COLORS.axis} />
              <YAxis stroke={CHART_COLORS.axis} />
              <Tooltip />
              <Line type="monotone" dataKey="interactions" stroke={CHART_COLORS.interactions} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className={styles['chart-card']}>
          <h3>成本趋势</h3>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={billingStats?.trend || []}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
              <XAxis dataKey="date" stroke={CHART_COLORS.axis} fontSize={10} />
              <YAxis stroke={CHART_COLORS.axis} />
              <Tooltip formatter={(value: number) => formatCurrency(value, billingStats?.currency)} />
              <Line type="monotone" dataKey="cost" stroke={CHART_COLORS.cost} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* 模型使用柱状图 */}
      {getModelBarData().length > 0 && (
        <div className={styles['chart-card']} style={{ marginBottom: '24px' }}>
          <h3>模型调用成本分布</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={getModelBarData()}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
              <XAxis dataKey="name" stroke={CHART_COLORS.axis} fontSize={11} />
              <YAxis stroke={CHART_COLORS.axis} />
              <Tooltip formatter={(value: number) => formatCurrency(value, billingStats?.currency)} />
              <Bar dataKey="cost" fill={CHART_COLORS.interactions} radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* 意图排行 */}
      <div className={styles['bottom-grid']}>
        <div className={styles['top-intents-card']}>
          <h3>最常用的意图</h3>
          <ul className={styles['intent-list']}>
            {(stats?.top_intents || []).length === 0 ? (
              <li className={styles['empty-hint']}>暂无数据</li>
            ) : (
              (stats?.top_intents || []).map((intent: Intent, index: number) => (
                <li key={index}>
                  <span className={styles['intent-rank']}>#{index + 1}</span>
                  <span className={styles['intent-name']}>{intent.intent}</span>
                  <span className={styles['intent-count']}>{intent.count}次</span>
                </li>
              ))
            )}
          </ul>
        </div>

        <div className={styles['top-intents-card']}>
          <h3>模型使用分布</h3>
          <ul className={styles['intent-list']}>
            {(billingStats?.by_model || []).length === 0 ? (
              <li className={styles['empty-hint']}>暂无数据</li>
            ) : (
              (billingStats?.by_model || []).slice(0, 5).map((model, index: number) => (
                <li key={index}>
                  <span className={styles['intent-rank']}>#{index + 1}</span>
                  <span className={styles['intent-name']}>{model.provider}:{model.model}</span>
                  <span className={styles['intent-count']}>{formatCurrency(model.cost, billingStats?.currency)}</span>
                </li>
              ))
            )}
          </ul>
        </div>
      </div>
    </div>
  )
}

export default DashboardPage
