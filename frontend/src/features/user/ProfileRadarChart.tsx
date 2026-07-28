/**
 * 画像类别分布雷达图——使用 SVG 纯实现，不依赖额外图表库。
 */

import { PROFILE_CATEGORY_LABELS } from './profileCategoryLabels'
import styles from './ProfileRadarChart.module.css'

interface Props {
  data: Record<string, number>
}

/** 类别优先级排序 */
const CATEGORY_ORDER = [
  'identity', 'preference', 'expertise', 'behavior',
  'goal', 'communication_style', 'emotional_state', 'context',
]

function ProfileRadarChart({ data }: Props) {
  const categories = CATEGORY_ORDER.filter((c) => data[c] !== undefined)
  if (categories.length === 0) {
    categories.push(...Object.keys(data))
  }

  const maxVal = Math.max(1, ...Object.values(data))
  const levels = 4
  const size = 260
  const cx = size / 2
  const cy = size / 2
  const radius = size * 0.38
  const angleSlice = (2 * Math.PI) / categories.length

  const getPoint = (i: number, value: number) => {
    const angle = angleSlice * i - Math.PI / 2
    const r = (value / maxVal) * radius
    return {
      x: cx + r * Math.cos(angle),
      y: cy + r * Math.sin(angle),
    }
  }

  // 背景网格
  const gridPolygons = Array.from({ length: levels }, (_, level) => {
    const r = ((level + 1) / levels) * radius
    const points = categories
      .map((_, i) => {
        const angle = angleSlice * i - Math.PI / 2
        return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`
      })
      .join(' ')
    return <polygon key={level} points={points} className={styles['grid-polygon']} />
  })

  // 轴线
  const axes = categories.map((_, i) => {
    const end = getPoint(i, maxVal)
    return <line key={i} x1={cx} y1={cy} x2={end.x} y2={end.y} className={styles['axis']} />
  })

  // 数据多边形
  const dataPoints = categories.map((cat, i) => {
    const val = data[cat] || 0
    return getPoint(i, val)
  })
  const dataPolygon = dataPoints.map((p) => `${p.x},${p.y}`).join(' ')

  // 标签
  const labels = categories.map((cat, i) => {
    const pos = getPoint(i, maxVal * 1.25)
    const label = PROFILE_CATEGORY_LABELS[cat] || cat
    return (
      <text
        key={i}
        x={pos.x}
        y={pos.y}
        textAnchor="middle"
        dominantBaseline="middle"
        className={styles['label']}
      >
        {label}
      </text>
    )
  })

  return (
    <div className={styles['radar-container']}>
      <svg viewBox={`0 0 ${size} ${size}`} className={styles['radar-svg']}>
        {gridPolygons}
        {axes}
        <polygon points={dataPolygon} className={styles['data-polygon']} />
        {dataPoints.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={4} className={styles['data-point']} />
        ))}
        {labels}
      </svg>
      <div className={styles['legend']}>
        {categories.map((cat) => (
          <div key={cat} className={styles['legend-item']}>
            <span className={styles['legend-dot']} />
            <span>{PROFILE_CATEGORY_LABELS[cat] || cat}</span>
            <span className={styles['legend-val']}>{data[cat] || 0}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default ProfileRadarChart
