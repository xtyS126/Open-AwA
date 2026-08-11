import { useId } from 'react'
import styles from './BrandMark.module.css'

interface BrandMarkProps {
  size?: number
  decorative?: boolean
}

/**
 * Open-AwA 抽象软晶标记。
 * 构形只使用圆角底板、外部软晶、内部软晶与留白切口，不表达字母或角色。
 */
export function BrandMark({ size = 56, decorative = false }: BrandMarkProps) {
  const gradientId = `soft-crystal-${useId().replace(/:/g, '')}`

  return (
    <svg
      className={styles['brand-mark']}
      style={{ width: size, height: size }}
      viewBox="0 0 64 64"
      fill="none"
      role={decorative ? undefined : 'img'}
      aria-label={decorative ? undefined : 'Open-AwA 抽象标记'}
      aria-hidden={decorative ? 'true' : undefined}
    >
      <defs>
        <linearGradient id={gradientId} x1="8" y1="56" x2="56" y2="8">
          <stop stopColor="var(--brand-violet-deep, #5e3fd6)" />
          <stop offset="1" stopColor="var(--brand-violet-light, #a678ff)" />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" fill={`url(#${gradientId})`} />
      <path
        d="M16.5 31.5C16.5 20.1 24.1 12.7 34.4 12.7c10.1 0 17.3 7.1 17.3 17.1 0 11.7-8.7 21.5-20.5 21.5-9.5 0-16.7-6.6-16.7-15.1 0-1.8.7-3.4 2-4.7Z"
        fill="var(--brand-cream, #fff9f5)"
      />
      <path
        d="M23.5 31.3c0-7.4 5.1-12.4 12.1-12.4 6.5 0 10.9 4.7 10.9 11.1 0 8.1-5.8 14.7-13.5 14.7-6.2 0-10.7-4.1-10.7-9.5 0-1.5.4-2.8 1.2-3.9Z"
        fill="var(--brand-violet, #7654ff)"
      />
      <path
        d="M39.3 23.9c3.2 1.8 4.7 5 3.9 8.2-.7 3-3.1 5.4-6.3 6.4.9-4.5-.2-8.4-3.4-11.4 1.6-2 3.7-3.2 5.8-3.2Z"
        fill="var(--brand-peach-light, #ffd8c8)"
      />
    </svg>
  )
}

export default BrandMark
