import { useState, useEffect, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, RefreshCw, Eye } from 'lucide-react'
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
import {
  billingAPI,
  syncModelCatalog,
  CostStatistics,
  UsageRecord,
  BudgetStatus,
  CatalogSyncResult,
} from '@/features/billing/billingApi'
import { useAuthStore } from '@/shared/store/authStore'
import { useToast } from '@/shared/components/Toast'
import UsageDetailDrawer from './components/UsageDetailDrawer'
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

/** 计数方法中文标签映射 —— 与 UsageDetailDrawer 保持一致 */
const METHOD_LABELS: Record<NonNullable<UsageRecord['method']>, string> = {
  api_usage: 'API',
  stream: '流式',
  tiktoken: 'tiktoken',
  ratio: '字符比率',
}

/** 判断当前用户是否为 admin 角色 */
function checkIsAdmin(role: string | undefined): boolean {
  return role === 'admin'
}

function BillingPage() {
  // 通过 useContext 获取当前 QueryClient（测试时可注入独立实例，避免污染全局）
  const queryClient = useQueryClient()
  // 周期选择为本地用户输入状态，保留 useState
  const [period, setPeriod] = useState<'daily' | 'weekly' | 'monthly' | 'yearly'>('monthly')
  // 上次更新时间为派生 UI 状态，保留 useState（在数据成功加载后更新）
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null)
  // 导出操作的本地错误状态（不依赖服务端查询）
  const [exportError, setExportError] = useState<string | null>(null)

  // 模型目录同步对话框状态（admin 专用）
  const [isSyncDialogOpen, setIsSyncDialogOpen] = useState(false)
  // 同步进行中标记（控制按钮 loading 与重复点击）
  const [isSyncing, setIsSyncing] = useState(false)

  // 用量详情抽屉状态
  const [selectedRecord, setSelectedRecord] = useState<UsageRecord | null>(null)
  const [isDetailDrawerOpen, setIsDetailDrawerOpen] = useState(false)

  // 当前用户信息 —— 用于判断是否显示 admin 同步按钮
  const user = useAuthStore((s) => s.user)
  const isAdmin = checkIsAdmin(user?.role)

  // Toast 通知 —— 同步结果/错误反馈
  const { addToast, ToastContainer } = useToast()

  // 成本统计查询 —— period 变化时自动刷新
  const statsQuery = useQuery<CostStatistics>({
    queryKey: ['billing', 'stats', period],
    queryFn: async () => {
      const response = await billingAPI.getCostStatistics({ period })
      return response.data
    },
  })

  // 用量明细查询 —— 与统计独立，互不阻塞
  const usageQuery = useQuery<UsageRecord[]>({
    queryKey: ['billing', 'usage', period],
    queryFn: async () => {
      const response = await billingAPI.getUsage({ limit: 50 })
      return response.data.records || []
    },
  })

  // 预算状态查询 —— 后端可能未配置预算，失败时降级为 null
  const budgetQuery = useQuery<BudgetStatus | null>({
    queryKey: ['billing', 'budget'],
    queryFn: async () => {
      const response = await billingAPI.getBudget('current').catch(() => ({ data: null }))
      return response.data
    },
  })

  const statistics = statsQuery.data ?? null
  const usageRecords = usageQuery.data ?? []
  const budgetStatus = budgetQuery.data ?? null

  // 派生 loading / refreshing / error 状态
  // isInitialLoading 表示首次加载（无缓存数据），对应原 loading 状态
  const loading = statsQuery.isInitialLoading && !statistics
  // 任一查询后台刷新中即视为"同步中"
  const refreshing = statsQuery.isFetching && !statsQuery.isInitialLoading
  // 优先展示统计查询错误，其次展示用量查询错误
  const error = statsQuery.error
    ? (statsQuery.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '加载计费数据失败'
    : usageQuery.error
      ? (usageQuery.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '加载用量明细失败'
      : null

  // 数据成功加载后更新"最近更新"时间戳
  useEffect(() => {
    if (statsQuery.isSuccess && statsQuery.data) {
      setLastUpdatedAt(new Date())
    }
  }, [statsQuery.dataUpdatedAt, statsQuery.isSuccess, statsQuery.data])

  // 监听计费用量更新事件 —— 改为 queryClient.invalidateQueries 触发后台刷新
  useEffect(() => {
    const handleUsageUpdated = () => {
      // 失效所有 ['billing', ...] 查询，TanStack Query 会在 staleTime 后自动重新获取
      // 此处主动触发重新获取，保证用户立即看到最新数据
      void queryClient.invalidateQueries({ queryKey: ['billing'] })
    }

    window.addEventListener(BILLING_USAGE_UPDATED_EVENT, handleUsageUpdated)
    return () => window.removeEventListener(BILLING_USAGE_UPDATED_EVENT, handleUsageUpdated)
  }, [queryClient])

  const handleExport = async () => {
    try {
      setExportError(null)
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
    } catch {
      setExportError('导出失败')
    }
  }

  /**
   * 执行模型目录同步。
   *
   * 调用 POST /api/billing/sync-catalog，从 models.dev / openrouter.ai 拉取最新模型与定价。
   * 成功时展示统计 toast 并刷新模型列表；失败时展示错误 toast。
   * 同步过程中按钮显示 loading 状态，防止重复点击。
   */
  const handleSyncCatalog = useCallback(async () => {
    setIsSyncing(true)
    try {
      const result: CatalogSyncResult = await syncModelCatalog()
      addToast(
        `同步完成：新增 ${result.added} 个，更新 ${result.updated} 个，失效 ${result.removed} 个，跳过 ${result.skipped} 个`,
        'success'
      )
      setIsSyncDialogOpen(false)
      // 刷新模型列表与用量数据，确保展示最新定价
      void queryClient.invalidateQueries({ queryKey: ['billing'] })
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : '模型目录同步失败'
      // 兼容 axios 错误响应中的 detail 字段
      const axiosErr = e as { response?: { data?: { detail?: string } } }
      const detail = axiosErr?.response?.data?.detail
      addToast(detail || errMsg, 'error')
    } finally {
      setIsSyncing(false)
    }
  }, [addToast, queryClient])

  /** 打开用量详情抽屉 */
  const handleOpenDetail = useCallback((record: UsageRecord) => {
    setSelectedRecord(record)
    setIsDetailDrawerOpen(true)
  }, [])

  /** 关闭用量详情抽屉 */
  const handleCloseDetail = useCallback(() => {
    setIsDetailDrawerOpen(false)
  }, [])

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

  /** 格式化可选 token 字段，0 或缺失时显示 "-" */
  const formatOptionalTokens = (tokens: number | undefined): string => {
    if (!tokens || tokens <= 0) return '-'
    return formatTokens(tokens)
  }

  /** 格式化缓存成本合计（cache_read_cost + cache_write_cost），保留 6 位小数 */
  const formatCacheCost = (record: UsageRecord): string => {
    const read = record.cache_read_cost ?? 0
    const write = record.cache_write_cost ?? 0
    const total = read + write
    if (total <= 0) return '-'
    const symbol = record.currency === 'CNY' ? '¥' : '$'
    return `${symbol}${total.toFixed(6)}`
  }

  /** 渲染计数方法标签 */
  const renderMethodTag = (record: UsageRecord) => {
    if (!record.method) return <span className={styles['method-tag']}>-</span>
    const label = METHOD_LABELS[record.method]
    return (
      <span style={{ display: 'inline-flex', gap: '4px', alignItems: 'center' }}>
        <span className={styles['method-tag']}>{label}</span>
        {record.estimated !== undefined && (
          <span className={`${styles['precision-badge']} ${record.estimated ? styles['estimated'] : styles['exact']}`}>
            {record.estimated ? '估算' : '精确'}
          </span>
        )}
      </span>
    )
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
          </select>
          <button className={styles['export-btn']} onClick={handleExport}>
            <Download size={14} />
            导出CSV
          </button>
          {/* 模型目录同步按钮 —— 仅 admin 角色可见 */}
          {isAdmin && (
            <button
              className={styles['sync-catalog-btn']}
              onClick={() => setIsSyncDialogOpen(true)}
              disabled={isSyncing}
              aria-label="同步模型目录"
              type="button"
            >
              <RefreshCw size={14} />
              {isSyncing ? '同步中...' : '同步模型目录'}
            </button>
          )}
        </div>
      </div>

      {/* 导出操作错误提示（独立于服务端查询错误） */}
      {exportError && <div className={styles['error-message']}>{exportError}</div>}

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
              <th>缓存读取Tokens</th>
              <th>缓存写入Tokens</th>
              <th>缓存成本</th>
              <th>思考Tokens</th>
              <th>计数方法</th>
              <th>成本</th>
              <th>耗时</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {usageRecords.length === 0 ? (
              <tr>
                <td colSpan={14} style={{ textAlign: 'center', color: 'var(--color-text-tertiary)' }}>
                  暂无数据
                </td>
              </tr>
            ) : (
              usageRecords.map((record) => (
                <tr key={record.call_id}>
                  <td data-label="时间">{new Date(record.created_at).toLocaleString('zh-CN')}</td>
                  <td data-label="厂商">
                    <span className={`${styles['provider-badge']} ${styles[record.provider] || record.provider}`}>
                      {record.provider}
                    </span>
                  </td>
                  <td data-label="模型">{record.model}</td>
                  <td data-label="内容类型">
                    <span className={styles['content-type-badge']}>{record.content_type}</span>
                  </td>
                  <td data-label="输入Tokens">{formatTokens(record.input_tokens)}</td>
                  <td data-label="输出Tokens">{formatTokens(record.output_tokens)}</td>
                  <td data-label="缓存读取Tokens">{formatOptionalTokens(record.cache_read_tokens)}</td>
                  <td data-label="缓存写入Tokens">{formatOptionalTokens(record.cache_write_tokens)}</td>
                  <td data-label="缓存成本">{formatCacheCost(record)}</td>
                  <td data-label="思考Tokens">{formatOptionalTokens(record.thoughts_tokens)}</td>
                  <td data-label="计数方法">{renderMethodTag(record)}</td>
                  <td data-label="成本">
                    {formatCurrency(record.total_cost, record.currency)}
                    {record.cache_hit && <span className={styles['cache-badge']}>缓存</span>}
                  </td>
                  <td data-label="耗时">{record.duration_ms}ms</td>
                  <td data-label="操作">
                    <button
                      className={styles['detail-btn']}
                      onClick={() => handleOpenDetail(record)}
                      type="button"
                      aria-label={`查看 ${record.model} 调用详情`}
                    >
                      <Eye size={12} />
                      详情
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* 模型目录同步确认对话框 —— 仅 admin 可触发 */}
      {isSyncDialogOpen && (
        <div
          className={styles['sync-dialog-overlay']}
          onClick={() => !isSyncing && setIsSyncDialogOpen(false)}
          role="presentation"
        >
          <div
            className={styles['sync-dialog']}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="sync-dialog-title"
          >
            <h3 id="sync-dialog-title" className={styles['sync-dialog-title']}>同步模型目录</h3>
            <div className={styles['sync-dialog-content']}>
              此操作将从 <strong>models.dev</strong> 和 <strong>openrouter.ai</strong> 拉取最新模型列表与定价。
              同步将覆盖本地未标记 <strong>user_overrides</strong> 的修改。是否继续？
            </div>
            <div className={styles['sync-dialog-actions']}>
              <button
                className={styles['sync-dialog-btn']}
                onClick={() => setIsSyncDialogOpen(false)}
                disabled={isSyncing}
                type="button"
              >
                取消
              </button>
              <button
                className={`${styles['sync-dialog-btn']} ${styles['primary']}`}
                onClick={handleSyncCatalog}
                disabled={isSyncing}
                type="button"
              >
                {isSyncing ? '同步中...' : '确认同步'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 用量详情抽屉 */}
      <UsageDetailDrawer
        record={selectedRecord}
        open={isDetailDrawerOpen}
        onClose={handleCloseDetail}
      />

      {/* Toast 通知容器 —— 同步结果/错误反馈 */}
      <ToastContainer />
    </div>
  )
}

export default BillingPage
