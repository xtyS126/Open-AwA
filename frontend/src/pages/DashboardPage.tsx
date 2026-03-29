import { useState, useEffect } from 'react'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { behaviorAPI } from '../services/api'
import { billingAPI } from '../services/billingApi'
import { BehaviorStats, BillingStats, Intent } from '../types/dashboard'
import './DashboardPage.css'

const CHART_COLORS = {
  grid: 'var(--color-chart-grid)',
  axis: 'var(--color-chart-axis)',
  interactions: 'var(--color-chart-primary)',
  cost: 'var(--color-chart-secondary)'
}

function DashboardPage() {
  const [stats, setStats] = useState<BehaviorStats | null>(null)
  const [billingStats, setBillingStats] = useState<BillingStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadStats()
  }, [])

  const loadStats = async () => {
    try {
      const [behaviorRes, billingRes] = await Promise.all([
        behaviorAPI.getStats(7),
        billingAPI.getCostStatistics({ period: 'monthly' }).catch(() => ({ data: null }))
      ])
      setStats(behaviorRes.data)
      setBillingStats(billingRes.data)
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

  if (loading) {
    return <div className="loading">加载中...</div>
  }

  return (
    <div className="dashboard-page">
      <div className="dashboard-header">
        <h1>仪表盘</h1>
      </div>

      <div className="stats-grid">
        <div className="stat-card">
          <h3>总交互次数</h3>
          <p className="stat-value">{stats?.total_interactions || 0}</p>
        </div>
        <div className="stat-card">
          <h3>工具使用次数</h3>
          <p className="stat-value">{stats?.total_tools_used || 0}</p>
        </div>
        <div className="stat-card">
          <h3>本月成本</h3>
          <p className="stat-value">{billingStats ? formatCurrency(billingStats.total_cost || 0, billingStats.currency) : '-'}</p>
        </div>
        <div className="stat-card">
          <h3>平均响应时间</h3>
          <p className="stat-value">{stats?.average_response_time || 0}s</p>
        </div>
      </div>

      <div className="charts-grid">
        <div className="chart-card">
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

        <div className="chart-card">
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

      <div className="top-intents-card">
        <h3>最常用的意图</h3>
        <ul className="intent-list">
          {(stats?.top_intents || []).map((intent: Intent, index: number) => (
            <li key={index}>
              <span className="intent-name">{intent.intent}</span>
              <span className="intent-count">{intent.count}次</span>
            </li>
          ))}
        </ul>
      </div>

      <div className="top-intents-card">
        <h3>模型使用分布</h3>
        <ul className="intent-list">
          {(billingStats?.by_model || []).slice(0, 5).map((model, index: number) => (
            <li key={index}>
              <span className="intent-name">{model.provider}:{model.model}</span>
              <span className="intent-count">{formatCurrency(model.cost, billingStats?.currency)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export default DashboardPage
