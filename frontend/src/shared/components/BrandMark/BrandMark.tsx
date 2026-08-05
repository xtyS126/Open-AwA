/**
 * Open-AwA 品牌标识（内联 SVG，与 public/logo.svg 一致）。
 * 双 A 形 + 中央微笑弧线，蓝紫渐变；页面内嵌使用避免额外请求。
 * size 控制渲染尺寸（px），颜色固定品牌渐变（双主题通用）。
 */
import styles from './BrandMark.module.css'

interface BrandMarkProps {
  /** 渲染尺寸 px，默认 56 */
  size?: number
}

export default function BrandMark({ size = 56 }: BrandMarkProps) {
  return (
    <svg
      className={styles['brand-mark']}
      style={{ width: size, height: size }}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="awaGradient" x1="0" y1="0" x2="32" y2="32">
          <stop offset="0%" stopColor="#3b82f6" />
          <stop offset="100%" stopColor="#6366f1" />
        </linearGradient>
      </defs>
      {/* 左侧 A 形眼睛 */}
      <path
        d="M4 26 L10 6 L16 26"
        stroke="url(#awaGradient)"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="10" cy="18" r="2.2" fill="url(#awaGradient)" />
      {/* 右侧 A 形眼睛 */}
      <path
        d="M16 26 L22 6 L28 26"
        stroke="url(#awaGradient)"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="22" cy="18" r="2.2" fill="url(#awaGradient)" />
      {/* 中央微笑弧线 / 连接桥梁 */}
      <path
        d="M10 23 Q16 29 22 23"
        stroke="url(#awaGradient)"
        strokeWidth="2"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  )
}
