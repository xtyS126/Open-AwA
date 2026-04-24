import { useState, useEffect, useCallback } from 'react'
import { Download } from 'lucide-react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  Legend
} from 'recharts'
import { billingAPI, CostStatistics, UsageRecord, BudgetStatus } from '@/features/billing/billingApi'
import { BILLING_USAGE_UPDATED_EVENT } from '@/shared/events/billingEvents'
import styles from './BillingPage.module.css'

const CHART_COLORS = {
  grid: 'var(--color-chart-grid)',
  axis: 'var(--color-chart-axis)',
  line: 'var(--color-chart-primary)',
  input: 'var(--color-chart-primary)',
  output: 'var(--color-chart-secondary)',
  pie: [
    'var(--color-chart-primary)',
    'var(--color-chart-secondary)',
    'var(--color-chart-3)',
    'var(--color-chart-4)',
    'var(--color-chart-5)',
    'var(--color-chart-6)'
  ]
}

function BillingPage() {
  const [statistics, setStatistics] = useState<CostStatistics | null>(null)
  const [usageRecords, setUsageRecords] = useState<UsageRecord[]>([])
  const [budgetStatus, setBudgetStatus] = useState<BudgetStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null)
  const [period, setPeriod] = useState<'daily' | 'weekly' | 'monthly' | 'yearly' | 'all'>('monthly')

  const loadBillingData = useCallback(async (options?: { silent?: boolean }) => {
    const silent = Boolean(options?.silent)
    try {
      if (silent) {
        setRefreshing(true)
      } else {
        setLoading(true)
      }
      setError(null)
      
      const [statsRes, usageRes, budgetRes] = await Promise.all([
        billingAPI.getCostStatistics({ period }),
        billingAPI.getUsage({ limit: 50 }),
        billingAPI.getBudget('current').catch(() => ({ data: null }))
      ])
      
      setStatistics(statsRes.data)
      setUsageRecords(usageRes.data.records || [])
      setBudgetStatus(budgetRes.data)
      setLastUpdatedAt(new Date())
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } }
      setError(axiosErr.response?.data?.detail || '加载计费数据失败')
    } finally {
      if (silent) {
        setRefreshing(false)
      } else {
        setLoading(false)
      }
    }
  }, [period])

  useEffect(() => {
    loadBillingData()
  }, [loadBillingData])

  useEffect(() => {
    const handleUsageUpdated = () => {
      loadBillingData({ silent: true })
    }

    window.addEventListener(BILLING_USAGE_UPDATED_EVENT, handleUsageUpdated)
    return () => window.removeEventListener(BILLING_USAGE_UPDATED_EVENT, handleUsageUpdated)
  }, [loadBillingData])

  const handleExport = async () => {
    try {
      const response = await billingAPI.getReport({ period, format: 'csv' })
      const csvContent = typeof response.data === 'string'
        ? response.data
        : typeof response.data?.content === 'string'
          ? response.data.content
          : ''
      if (!csvContent) {
        throw new Error('empty_report_content')
      }
      const blob = new Blob([csvContent], { type: 'text/csv' })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `billing-report-${period}-${new Date().toISOString().split('T')[0]}.csv`
      a.click()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      setError('导出失败')
    }
  }

  const formatCurrency = (amount: number, currency: string) => {
    const symbol = currency === 'CNY' ? '¥' : '$'
    return `${symbol}${amount.toFixed(6)}`
  }

  const formatCurrencyShort = (amount: number, currency: string) => {
    const symbol = currency === 'CNY' ? '¥' : '$'
    if (amount >= 1) return `${symbol}${amount.toFixed(2)}`
    return `${symbol}${amount.toFixed(4)}`
  }

  const formatTokens = (tokens: number) => {
    if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(2)}M`
    if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`
    return tokens.toString()
  }

  const getPieData = () => {
    if (!statistics?.by_model) return []
    return statistics.by_model.slice(0, 6).map((item, index) => ({
      name: `${item.provider}:${item.model}`,
      value: item.cost,
      color: CHART_COLORS.pie[index % CHART_COLORS.pie.length]
    }))
  }

  /* Token使用趋势数据（输入/输出分开展示） */
  const getTokenTrendData = () => {
    if (!statistics?.trend) return []
    return statistics.trend.map(t => ({
      date: t.date,
      input: t.input_tokens,
      output: t.output_tokens
    }))
  }

  /* 内容类型分布 */
  const getContentTypeData = () => {
    if (!statistics?.by_content_type) return []
    return Object.entries(statistics.by_content_type).map(([type, data], index) => ({
      name: type,
      tokens: data.tokens,
      cost: data.cost,
      color: CHART_COLORS.pie[index % CHART_COLORS.pie.length]
    }))
  }

  if (loading) {
    return <div className={styles['loading']}>加载计费数据...</div>
  }

  if (error) {
    return <div className={styles['error-message']}>{error}</div>
  }

  return (
    <div className={styles['billing-page']}>
      <div className={styles['billing-header']}>
        <div>
          <h1>用量计费</h1>
          <p className={styles['page-subtitle']}>查看 AI 模型调用的成本与用量统计</p>
          <div className={styles['sync-status']}>
            <span className={`${styles['sync-dot']} ${refreshing ? styles['sync-dot-refreshing'] : ''}`} />
            <span>{refreshing ? '同步中...' : '已开启聊天用量联动'}</span>
            {lastUpdatedAt && <span>最近更新: {lastUpdatedAt.toLocaleTimeString('zh-CN')}</span>}
          </div>
        </div>
        <div className={styles['header-actions']}>
          <select value={period} onChange={(e) => setPeriod(e.target.value as typeof period)}>
            <option value="daily">今日</option>
            <option value="weekly">本周</option>
            <option value="monthly">本月</option>
            <option value="yearly">本年</option>
            <option value="all">全部</option>
          </select>
          <button className={styles['export-btn']} onClick={handleExport}>
            <Download size={14} />
            导出CSV
          </button>
        </div>
      </div>

      {/* 预算状态条 */}
      {budgetStatus?.has_budget_configured && (
        <div className={`${styles['budget-bar']} ${budgetStatus.is_exceeded ? styles['budget-exceeded'] : budgetStatus.is_warning ? styles['budget-warning'] : ''}`}>
          <div className={styles['budget-info']}>
            <span>预算: {formatCurrencyShort(budgetStatus.current_usage || 0, budgetStatus.currency || 'USD')} / {formatCurrencyShort(budgetStatus.max_amount || 0, budgetStatus.currency || 'USD')}</span>
            <span className={styles['budget-pct']}>{(budgetStatus.usage_percentage || 0).toFixed(1)}%</span>
          </div>
          <div className={styles['budget-progress']}>
            <div
              className={styles['budget-progress-fill']}
              style={{ width: `${Math.min(budgetStatus.usage_percentage || 0, 100)}%` }}
            />
          </div>
        </div>
      )}

      <div className={styles['billing-stats-grid']}>
        <div className={styles['billing-stat-card']}>
          <h3>总成本</h3>
          <p className={styles['stat-value']}>
            {formatCurrencyShort(statistics?.total_cost || 0, statistics?.currency || 'USD')}
          </p>
          <p className={styles['stat-subtitle']}>
            {statistics?.period_start?.split('T')[0]} 至 {statistics?.period_end?.split('T')[0]}
          </p>
        </div>
        <div className={styles['billing-stat-card']}>
          <h3>输入Tokens</h3>
          <p className={styles['stat-value']}>{formatTokens(statistics?.total_input_tokens || 0)}</p>
          <p className={styles['stat-subtitle']}>输入tokens总量</p>
        </div>
        <div className={styles['billing-stat-card']}>
          <h3>输出Tokens</h3>
          <p className={styles['stat-value']}>{formatTokens(statistics?.total_output_tokens || 0)}</p>
          <p className={styles['stat-subtitle']}>输出tokens总量</p>
        </div>
        <div className={styles['billing-stat-card']}>
          <h3>API调用次数</h3>
          <p className={styles['stat-value']}>{statistics?.total_calls || 0}</p>
          <p className={styles['stat-subtitle']}>总调用次数</p>
        </div>
      </div>

      <div className={styles['billing-charts-grid']}>
        <div className={styles['billing-chart-card']}>
          <h3>成本趋势</h3>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={statistics?.trend || []}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
              <XAxis dataKey="date" stroke={CHART_COLORS.axis} fontSize={12} />
              <YAxis stroke={CHART_COLORS.axis} fontSize={12} />
              <Tooltip 
                formatter={(value: number) => formatCurrencyShort(value, statistics?.currency || 'USD')}
              />
              <Line 
                type="monotone" 
                dataKey="cost" 
                stroke={CHART_COLORS.line} 
                strokeWidth={2}
                dot={{ fill: CHART_COLORS.line, r: 3 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className={styles['billing-chart-card']}>
          <h3>模型使用分布</h3>
          <ResponsiveContainer width="100%" height={280}>
            <PieChart>
              <Pie
                data={getPieData()}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={100}
                paddingAngle={2}
                dataKey="value"
                label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}
                labelLine={false}
              >
                {getPieData().map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip formatter={(value: number) => formatCurrencyShort(value, statistics?.currency || 'USD')} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Token使用趋势（输入/输出分开） */}
      {getTokenTrendData().length > 0 && (
        <div className={styles['billing-chart-card']} style={{ marginBottom: '24px' }}>
          <h3>Token使用趋势</h3>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={getTokenTrendData()}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
              <XAxis dataKey="date" stroke={CHART_COLORS.axis} fontSize={11} />
              <YAxis stroke={CHART_COLORS.axis} fontSize={11} tickFormatter={(v) => formatTokens(v)} />
              <Tooltip formatter={(value: number) => formatTokens(value)} />
              <Legend />
              <Bar dataKey="input" name="输入Tokens" fill={CHART_COLORS.input} radius={[2, 2, 0, 0]} />
              <Bar dataKey="output" name="输出Tokens" fill={CHART_COLORS.output} radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* 内容类型分布 */}
      {getContentTypeData().length > 0 && (
        <div className={styles['billing-chart-card']} style={{ marginBottom: '24px' }}>
          <h3>内容类型分布</h3>
          <div className={styles['content-type-grid']}>
            {getContentTypeData().map((item) => (
              <div key={item.name} className={styles['content-type-item']}>
                <span className={styles['content-type-name']}>{item.name}</span>
                <span className={styles['content-type-tokens']}>{formatTokens(item.tokens)} tokens</span>
                <span className={styles['content-type-cost']}>{formatCurrencyShort(item.cost, statistics?.currency || 'USD')}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className={styles['billing-usage-table']}>
        <h3>用量明细</h3>
        <table className={styles['usage-table']}>
          <thead>
            <tr>
              <th>时间</th>
              <th>厂商</th>
              <th>模型</th>
              <th>内容类型</th>
              <th>输入Tokens</th>
              <th>输出Tokens</th>
              <th>成本</th>
              <th>耗时</th>
            </tr>
          </thead>
          <tbody>
            {usageRecords.length === 0 ? (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', color: 'var(--color-text-tertiary)' }}>
                  暂无数据
                </td>
              </tr>
            ) : (
              usageRecords.map((record) => (
                <tr key={record.call_id}>
                  <td>{new Date(record.created_at).toLocaleString('zh-CN')}</td>
                  <td>
                    <span className={`${styles['provider-badge']} ${styles[record.provider] || record.provider}`}>
                      {record.provider}
                    </span>
                  </td>
                  <td>{record.model}</td>
                  <td>
                    <span className={styles['content-type-badge']}>{record.content_type}</span>
                  </td>
                  <td>{formatTokens(record.input_tokens)}</td>
                  <td>{formatTokens(record.output_tokens)}</td>
                  <td>
                    {formatCurrency(record.total_cost, record.currency)}
                    {record.cache_hit && <span className={styles['cache-badge']}>缓存</span>}
                  </td>
                  <td>{record.duration_ms}ms</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default BillingPage
