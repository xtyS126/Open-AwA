/**
 * 仪表盘页面 —— 对齐 Canvas 设计参考 (open-awa-canvas/pages/dashboard.html)。
 * 结构：页面标题 / 4 列统计卡片 / 2 列折线图 / 4 列系统资源 / 最近活动表格 / 业务数据分区。
 * 数据获取逻辑保持不变，仅重构布局与可视化呈现。
 * 业务数据分区合并自原 DataDashboard（对话数/工具调用/平均响应时间/用户反馈/角色使用分布）。
 */
import { useState, useEffect, useMemo, memo, type ReactNode } from 'react'
import { BarChart3, MessageSquare, Wrench, Activity, ThumbsUp } from 'lucide-react'
import { behaviorAPI, skillsAPI, pluginsAPI, memoryAPI } from '@/shared/api/api'
import { billingAPI } from '@/features/billing/billingApi'
import { getDataStats, type DataStats } from '@/shared/api/dataApi'
import { BehaviorStats, BillingStats } from '@/features/dashboard/dashboard'
import { StatCard, Badge } from '@/shared/components/ui'
import styles from './DashboardPage.module.css'

/* ============================================================
 * 类型定义
 * ============================================================ */

/* 系统资源概览数据类型 */
interface SystemOverview {
  skillsTotal: number
  skillsEnabled: number
  pluginsTotal: number
  pluginsEnabled: number
  longTermMemories: number
}

/* 折线图数据点 */
interface ChartPoint {
  label: string
  value: number
}

/* 最近活动记录 —— status 对齐 Badge 组件变体（primary 即 Canvas 的 info 蓝色风格） */
interface ActivityRecord {
  time: string
  event: string
  status: 'success' | 'primary' | 'warning' | 'error'
  statusText: string
  icon: ReactNode
}

/* 折线图组件入参 */
interface LineChartProps {
  data: ChartPoint[]
  /* 折线与渐变颜色（CSS var() 或颜色值） */
  color: string
  /* 渐变唯一 ID，避免多图冲突 */
  gradientId: string
  /* Y 轴 4 档刻度标签，从下到上 */
  yAxisLabels: string[]
  /* 空数据占位文案 */
  emptyText?: string
}

/* ============================================================
 * SVG 图标组件 —— 内联保持文件自包含，尺寸统一 18x18 / 14x14
 * ============================================================ */

const svgBase = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

/* 交互趋势图标（折线心电波） */
const ActivityIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...svgBase}>
    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
  </svg>
)

/* 星形图标（技能） */
const StarIcon = ({ size = 18 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...svgBase}>
    <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
  </svg>
)

/* 插件图标（扳手） */
const PluginIcon = ({ size = 18 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" {...svgBase}>
    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" />
  </svg>
)

/* 美元图标（成本） */
const DollarIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...svgBase}>
    <line x1="12" y1="1" x2="12" y2="23" />
    <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
  </svg>
)

/* 书签图标（记忆） */
const BookmarkIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...svgBase}>
    <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
  </svg>
)

/* 广播图标（MCP） */
const BroadcastIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" {...svgBase}>
    <circle cx="12" cy="12" r="2" />
    <path d="M16.24 7.76a6 6 0 0 1 0 8.49m-8.48-.01a6 6 0 0 1 0-8.49m11.31-2.82a10 10 0 0 1 0 14.14m-14.14 0a10 10 0 0 1 0-14.14" />
  </svg>
)

/* 时钟图标（定时任务） */
const ClockIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" {...svgBase}>
    <circle cx="12" cy="12" r="10" />
    <polyline points="12 6 12 12 16 14" />
  </svg>
)

/* 错误图标（圆圈 + 叉） */
const ErrorCircleIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" {...svgBase}>
    <circle cx="12" cy="12" r="10" />
    <line x1="15" y1="9" x2="9" y2="15" />
    <line x1="9" y1="9" x2="15" y2="15" />
  </svg>
)

/* ============================================================
 * 可复用 SVG 折线图组件 —— 对齐 Canvas dashboard 图表规范
 * viewBox 0 0 400 180，含网格线 / 坐标轴标签 / 渐变填充 / 折线 / 数据点
 * ============================================================ */

/* 图表布局常量 —— 与 Canvas 参考保持一致 */
const CHART_LAYOUT = {
  width: 400,
  height: 180,
  axisLeftX: 40,
  axisRightX: 390,
  axisBottomY: 150,
  axisTopY: 10,
  firstPointX: 60,
  lastPointX: 385,
  pointRadius: 4,
}

/* 根据数据点索引与总数计算 X 坐标 */
const computePointX = (index: number, total: number): number => {
  if (total <= 1) return CHART_LAYOUT.firstPointX
  const step = (CHART_LAYOUT.lastPointX - CHART_LAYOUT.firstPointX) / (total - 1)
  return CHART_LAYOUT.firstPointX + step * index
}

/* 根据数值与最大值计算 Y 坐标（值越大 Y 越小，向上递增） */
const computePointY = (value: number, maxValue: number): number => {
  if (maxValue <= 0) return CHART_LAYOUT.axisBottomY
  const ratio = Math.min(value / maxValue, 1)
  return CHART_LAYOUT.axisBottomY - ratio * (CHART_LAYOUT.axisBottomY - CHART_LAYOUT.axisTopY)
}

const LineChart = memo(function LineChart({
  data,
  color,
  gradientId,
  yAxisLabels,
  emptyText = '暂无数据',
}: LineChartProps) {
  /* 计算坐标点 —— 仅依赖 data，避免不必要的重渲染 */
  const points = useMemo(() => {
    if (data.length === 0) return []
    const maxValue = Math.max(...data.map(d => d.value), 1)
    return data.map((d, i) => ({
      x: computePointX(i, data.length),
      y: computePointY(d.value, maxValue),
      ...d,
    }))
  }, [data])

  if (points.length === 0) {
    return (
      <div className={styles.chartEmpty} role="status">
        {emptyText}
      </div>
    )
  }

  const polylinePoints = points.map(p => `${p.x},${p.y}`).join(' ')
  /* 渐变填充区域路径：折线段 + 底部封闭回起点 */
  const areaPath =
    `M${points[0].x},${points[0].y} ` +
    points.slice(1).map(p => `L${p.x},${p.y}`).join(' ') +
    ` L${points[points.length - 1].x},${CHART_LAYOUT.axisBottomY}` +
    ` L${points[0].x},${CHART_LAYOUT.axisBottomY} Z`

  return (
    <svg
      viewBox={`0 0 ${CHART_LAYOUT.width} ${CHART_LAYOUT.height}`}
      className={styles.chartSvg}
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.2" />
          <stop offset="100%" stopColor={color} stopOpacity="0.01" />
        </linearGradient>
      </defs>

      {/* 网格线 —— 实线坐标轴 + 虚线中间刻度 */}
      <line x1={CHART_LAYOUT.axisLeftX} y1={CHART_LAYOUT.axisTopY} x2={CHART_LAYOUT.axisLeftX} y2={CHART_LAYOUT.axisBottomY} stroke="var(--color-border)" strokeWidth="1" />
      <line x1={CHART_LAYOUT.axisLeftX} y1={CHART_LAYOUT.axisBottomY} x2={CHART_LAYOUT.axisRightX} y2={CHART_LAYOUT.axisBottomY} stroke="var(--color-border)" strokeWidth="1" />
      <line x1={CHART_LAYOUT.axisLeftX} y1="115" x2={CHART_LAYOUT.axisRightX} y2="115" stroke="var(--color-border-subtle)" strokeWidth="0.5" strokeDasharray="4,4" />
      <line x1={CHART_LAYOUT.axisLeftX} y1="80" x2={CHART_LAYOUT.axisRightX} y2="80" stroke="var(--color-border-subtle)" strokeWidth="0.5" strokeDasharray="4,4" />
      <line x1={CHART_LAYOUT.axisLeftX} y1="45" x2={CHART_LAYOUT.axisRightX} y2="45" stroke="var(--color-border-subtle)" strokeWidth="0.5" strokeDasharray="4,4" />

      {/* Y 轴标签 —— 从下到上 4 档 */}
      <text x="30" y="154" textAnchor="end" fill="var(--color-text-tertiary)" fontSize="10">{yAxisLabels[0]}</text>
      <text x="30" y="119" textAnchor="end" fill="var(--color-text-tertiary)" fontSize="10">{yAxisLabels[1]}</text>
      <text x="30" y="84" textAnchor="end" fill="var(--color-text-tertiary)" fontSize="10">{yAxisLabels[2]}</text>
      <text x="30" y="49" textAnchor="end" fill="var(--color-text-tertiary)" fontSize="10">{yAxisLabels[3]}</text>

      {/* X 轴标签 —— 每个数据点对应一个 */}
      {points.map((p, i) => (
        <text key={`x-label-${i}`} x={p.x} y="168" textAnchor="middle" fill="var(--color-text-tertiary)" fontSize="10">{p.label}</text>
      ))}

      {/* 渐变填充区域 */}
      <path d={areaPath} fill={`url(#${gradientId})`} />

      {/* 折线 —— stroke-width 2.5，圆角连接 */}
      <polyline points={polylinePoints} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />

      {/* 数据点圆圈 —— 实心背景 + 彩色描边 */}
      {points.map((p, i) => (
        <circle key={`data-point-${i}`} cx={p.x} cy={p.y} r={CHART_LAYOUT.pointRadius} fill="var(--color-bg)" stroke={color} strokeWidth="2" />
      ))}
    </svg>
  )
})

/* ============================================================
 * 主页面组件
 * ============================================================ */

/* 最近活动占位数据 —— 当前无对应 API，沿用 Canvas 参考数据，后续接入日志接口后替换 */
const ACTIVITY_RECORDS: ActivityRecord[] = [
  {
    time: '14:23',
    event: '执行技能: web_search',
    status: 'success',
    statusText: '成功',
    icon: <StarIcon size={14} />,
  },
  {
    time: '14:15',
    event: '插件更新: data-chart v2.1',
    status: 'primary',
    statusText: '完成',
    icon: <PluginIcon size={14} />,
  },
  {
    time: '13:58',
    event: '定时任务: 每日报告',
    status: 'warning',
    statusText: '运行中',
    icon: <ClockIcon />,
  },
  {
    time: '13:42',
    event: '记忆写入: 会话 #1024 上下文',
    status: 'success',
    statusText: '成功',
    icon: <BookmarkIcon />,
  },
  {
    time: '13:30',
    event: 'MCP 连接: filesystem-server',
    status: 'primary',
    statusText: '已连接',
    icon: <BroadcastIcon />,
  },
  {
    time: '13:15',
    event: 'LLM 调用失败: provider timeout',
    status: 'error',
    statusText: '失败',
    icon: <ErrorCircleIcon />,
  },
]

function DashboardPage() {
  const [stats, setStats] = useState<BehaviorStats | null>(null)
  const [billingStats, setBillingStats] = useState<BillingStats | null>(null)
  const [systemOverview, setSystemOverview] = useState<SystemOverview>({
    skillsTotal: 0,
    skillsEnabled: 0,
    pluginsTotal: 0,
    pluginsEnabled: 0,
    longTermMemories: 0,
  })
  const [loading, setLoading] = useState(true)
  /* 业务数据状态 —— 合并自 DataDashboard，独立于系统概览，加载失败时为 null */
  const [dataStats, setDataStats] = useState<DataStats | null>(null)

  const loadStats = async () => {
    try {
      /* 并发加载所有数据源 —— 保持原有调用不变，业务数据并行拉取 */
      const [behaviorRes, billingRes, skillsRes, pluginsRes, memoryRes, dataRes] = await Promise.all([
        behaviorAPI.getStats(7).catch(() => ({ data: null })),
        billingAPI.getCostStatistics({ period: 'monthly' }).catch(() => ({ data: null })),
        skillsAPI.getAll().catch(() => ({ data: [] })),
        pluginsAPI.getAll().catch(() => ({ data: [] })),
        memoryAPI.getLongTerm().catch(() => ({ data: [] })),
        getDataStats().catch(() => null),
      ])
      setStats(behaviorRes.data)
      setBillingStats(billingRes.data)
      setDataStats(dataRes)

      /* 从真实接口汇总系统概览（API 返回裸数组） */
      const skillsList = Array.isArray(skillsRes.data) ? skillsRes.data : []
      const pluginsList = Array.isArray(pluginsRes.data) ? pluginsRes.data : []
      const memoriesList = Array.isArray(memoryRes.data) ? memoryRes.data : []

      setSystemOverview({
        skillsTotal: skillsList.length,
        skillsEnabled: skillsList.filter((s: { enabled?: boolean }) => s.enabled).length,
        pluginsTotal: pluginsList.length,
        pluginsEnabled: pluginsList.filter((p: { enabled?: boolean }) => p.enabled).length,
        longTermMemories: memoriesList.length,
      })
    } catch {
      setStats(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadStats()
  }, [])

  /* 货币格式化 —— 保持原有实现 */
  const formatCurrency = (amount: number, currency: string = 'USD') => {
    const symbol = currency === 'CNY' ? '¥' : '$'
    return `${symbol}${amount.toFixed(2)}`
  }

  /* 交互趋势数据映射 —— 缺失时返回空数组触发占位 */
  const interactionChartData = useMemo<ChartPoint[]>(() => {
    const raw = stats?.chart_data || []
    if (raw.length === 0) return []
    return raw.map(d => ({ label: d.day, value: d.interactions }))
  }, [stats])

  /* 成本趋势数据映射 */
  const costChartData = useMemo<ChartPoint[]>(() => {
    const raw = billingStats?.trend || []
    if (raw.length === 0) return []
    return raw.map(d => ({ label: d.date, value: d.cost }))
  }, [billingStats])

  /* Y 轴刻度生成 —— 取数据最大值向上取整生成 4 档刻度 */
  const buildYAxis = (maxValue: number, prefix = ''): string[] => {
    if (maxValue <= 0) return [`${prefix}0`, `${prefix}0`, `${prefix}0`, `${prefix}0`]
    const niceMax = Math.ceil(maxValue)
    const step = niceMax / 3
    return [
      `${prefix}0`,
      `${prefix}${Math.round(step)}`,
      `${prefix}${Math.round(step * 2)}`,
      `${prefix}${niceMax}`,
    ]
  }

  /* 交互趋势 Y 轴刻度 */
  const interactionYAxis = useMemo(() => {
    const max = interactionChartData.length > 0
      ? Math.max(...interactionChartData.map(d => d.value))
      : 0
    return buildYAxis(max)
  }, [interactionChartData])

  /* 成本趋势 Y 轴刻度 */
  const costYAxis = useMemo(() => {
    const max = costChartData.length > 0
      ? Math.max(...costChartData.map(d => d.value))
      : 0
    return buildYAxis(max, '$')
  }, [costChartData])

  /* 角色使用分布最大值 —— 用于条形图百分比计算（合并自 DataDashboard） */
  const maxRoleCount = useMemo(() => {
    if (!dataStats || dataStats.role_usage.length === 0) return 0
    return Math.max(...dataStats.role_usage.map(r => r.count))
  }, [dataStats])

  if (loading) {
    return <div className={styles.loading}>加载中...</div>
  }

  const totalCost = billingStats?.total_cost || 0
  const currency = billingStats?.currency || 'USD'
  const totalInteractions = stats?.total_interactions || 0

  return (
    <div className={styles.dashboardPage}>
      {/* 页面标题 */}
      <div className={styles.pageHeader}>
        <h1 className={styles.pageTitle}>仪表盘</h1>
        <p className={styles.pageSubtitle}>系统运行状态概览</p>
      </div>

      {/* ========== 统计卡片行 ========== */}
      <div className={styles.statGrid}>
        <StatCard
          label="今日交互"
          value={totalInteractions.toLocaleString()}
          accentColor="var(--color-primary)"
          icon={<ActivityIcon />}
          trend={<Badge variant="success" text="近7天" />}
        />
        <StatCard
          label="活跃技能"
          value={`${systemOverview.skillsEnabled}/${systemOverview.skillsTotal}`}
          accentColor="var(--color-warning)"
          icon={<StarIcon />}
          trend={<span className={styles.trendHint}>已启用 / 总计</span>}
        />
        <StatCard
          label="运行插件"
          value={systemOverview.pluginsEnabled}
          accentColor="var(--color-chart-5)"
          icon={<PluginIcon />}
          trend={<Badge variant="primary" text="运行中" />}
        />
        <StatCard
          label="成本消耗"
          value={formatCurrency(totalCost, currency)}
          accentColor="var(--color-success)"
          icon={<DollarIcon />}
          trend={<Badge variant="success" text="本月" />}
        />
      </div>

      {/* ========== 图表区域（双列） ========== */}
      <div className={styles.chartGrid}>
        <div className={styles.chartContainer}>
          <h3 className={styles.chartTitle}>近7天交互趋势</h3>
          <LineChart
            data={interactionChartData}
            color="var(--color-primary)"
            gradientId="interactionGrad"
            yAxisLabels={interactionYAxis}
            emptyText="暂无交互数据"
          />
        </div>
        <div className={styles.chartContainer}>
          <h3 className={styles.chartTitle}>成本趋势</h3>
          <LineChart
            data={costChartData}
            color="var(--color-chart-secondary)"
            gradientId="costGrad"
            yAxisLabels={costYAxis}
            emptyText="暂无成本数据"
          />
        </div>
      </div>

      {/* ========== 系统资源区域 ========== */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>系统资源</h2>
        <div className={styles.systemGrid}>
          <div className={styles.systemCard}>
            <div className={styles.systemCardHeader}>
              <div className={styles.systemIconBox} style={{ background: 'var(--color-primary-soft-bg)' }}>
                <span style={{ color: 'var(--color-primary)' }}><StarIcon /></span>
              </div>
              <div className={styles.systemMeta}>
                <div className={styles.systemName}>技能引擎</div>
                <Badge variant="success" text="运行中" className={styles.systemBadge} />
              </div>
            </div>
            <div className={styles.systemCount}>{systemOverview.skillsEnabled} active / {systemOverview.skillsTotal} total</div>
          </div>

          <div className={styles.systemCard}>
            <div className={styles.systemCardHeader}>
              <div className={styles.systemIconBox} style={{ background: 'var(--color-tag-purple-bg)' }}>
                <span style={{ color: 'var(--color-tag-purple-text)' }}><PluginIcon /></span>
              </div>
              <div className={styles.systemMeta}>
                <div className={styles.systemName}>插件系统</div>
                <Badge variant="success" text="运行中" className={styles.systemBadge} />
              </div>
            </div>
            <div className={styles.systemCount}>{systemOverview.pluginsEnabled} active</div>
          </div>

          <div className={styles.systemCard}>
            <div className={styles.systemCardHeader}>
              <div className={styles.systemIconBox} style={{ background: 'var(--color-warning-bg)' }}>
                <span style={{ color: 'var(--color-warning-strong)' }}><BookmarkIcon /></span>
              </div>
              <div className={styles.systemMeta}>
                <div className={styles.systemName}>记忆系统</div>
                <Badge variant="success" text="运行中" className={styles.systemBadge} />
              </div>
            </div>
            <div className={styles.systemCount}>{systemOverview.longTermMemories.toLocaleString()} 长期记忆</div>
          </div>

          <div className={styles.systemCard}>
            <div className={styles.systemCardHeader}>
              <div className={styles.systemIconBox} style={{ background: 'var(--color-success-bg)' }}>
                <span style={{ color: 'var(--color-success-strong)' }}><BroadcastIcon /></span>
              </div>
              <div className={styles.systemMeta}>
                <div className={styles.systemName}>MCP 服务</div>
                <Badge variant="success" text="运行中" className={styles.systemBadge} />
              </div>
            </div>
            <div className={styles.systemCount}>可用</div>
          </div>
        </div>
      </div>

      {/* ========== 最近活动区域 ========== */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>最近活动</h2>
        <div className={styles.activityWrap}>
          <table className={styles.activityTable}>
            <thead>
              <tr>
                <th>时间</th>
                <th>事件</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {ACTIVITY_RECORDS.map((record, idx) => (
                <tr key={`activity-${idx}`}>
                  <td className={styles.timeCell}>{record.time}</td>
                  <td>
                    <div className={styles.eventCell}>
                      <span className={styles.eventIcon}>{record.icon}</span>
                      <span>{record.event}</span>
                    </div>
                  </td>
                  <td>
                    <Badge variant={record.status} text={record.statusText} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ========== 业务数据分区（合并自 DataDashboard） ========== */}
      <div className={styles.section}>
        <h2 className={styles.sectionTitle}>业务数据</h2>

        {dataStats ? (
          <>
            {/* 业务统计卡片 —— 对话数 / 工具调用 / 平均响应时间 / 用户反馈 */}
            <div className={styles.bizStatsGrid}>
              <div className={styles.bizStatCard}>
                <MessageSquare size={24} className={styles.bizStatIcon} />
                <div className={styles.bizStatInfo}>
                  <span className={styles.bizStatValue}>{dataStats.conversation_count}</span>
                  <span className={styles.bizStatLabel}>对话数</span>
                </div>
              </div>
              <div className={styles.bizStatCard}>
                <Wrench size={24} className={styles.bizStatIcon} />
                <div className={styles.bizStatInfo}>
                  <span className={styles.bizStatValue}>{dataStats.tool_call_count}</span>
                  <span className={styles.bizStatLabel}>工具调用</span>
                </div>
              </div>
              <div className={styles.bizStatCard}>
                <Activity size={24} className={styles.bizStatIcon} />
                <div className={styles.bizStatInfo}>
                  <span className={styles.bizStatValue}>{dataStats.avg_response_time_ms.toFixed(0)}ms</span>
                  <span className={styles.bizStatLabel}>平均响应时间</span>
                </div>
              </div>
              <div className={styles.bizStatCard}>
                <ThumbsUp size={24} className={styles.bizStatIcon} />
                <div className={styles.bizStatInfo}>
                  <span className={styles.bizStatValue}>{dataStats.feedback_count}</span>
                  <span className={styles.bizStatLabel}>用户反馈</span>
                </div>
              </div>
            </div>

            {/* 角色使用分布条形图 */}
            {dataStats.role_usage.length > 0 && (
              <div className={styles.bizRoleCard}>
                <h3 className={styles.bizRoleTitle}>
                  <BarChart3 size={18} />
                  角色使用分布
                </h3>
                <div className={styles.roleUsageList}>
                  {dataStats.role_usage.map(item => (
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
              </div>
            )}
          </>
        ) : (
          <div className={styles.bizEmpty} role="status">暂无业务数据</div>
        )}
      </div>
    </div>
  )
}

export default DashboardPage
