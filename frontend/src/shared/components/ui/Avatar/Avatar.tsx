/**
 * Avatar 头像组件 — 支持图片展示或文字首字母回退。
 * 支持三种尺寸和两种形状，图片加载失败自动回退到文字。
 * 支持从 CSS 变量读取自定义形状和边框样式。
 */
import React, { useState, useCallback, useMemo } from 'react'
import styles from './Avatar.module.css'

type AvatarSize = 'sm' | 'md' | 'lg'
type AvatarShape = 'circle' | 'rounded'

interface AvatarProps {
  src?: string
  alt?: string
  size?: AvatarSize
  shape?: AvatarShape
  className?: string
}

const sizeMap: Record<AvatarSize, number> = {
  sm: 24,
  md: 32,
  lg: 40,
}

const Avatar: React.FC<AvatarProps> = ({
  src,
  alt = '',
  size = 'md',
  shape = 'circle',
  className = '',
}) => {
  const [imgError, setImgError] = useState(false)

  const handleError = useCallback(() => {
    setImgError(true)
  }, [])

  const dimension = sizeMap[size]
  const fallbackText = alt ? alt.charAt(0).toUpperCase() : ''

  const containerCls = [
    styles.avatar,
    styles[size],
    styles[shape],
    className,
  ].filter(Boolean).join(' ')

  // 使用 useMemo 缓存样式对象，避免每次渲染都重新计算
  const customStyle = useMemo(() => {
    const style: React.CSSProperties = { width: dimension, height: dimension }
    // CSS 变量已在 CSS Module 中通过 var() 引用，无需 JS 读取
    return style
  }, [dimension])

  // 无图片或加载失败时展示文字回退
  if (!src || imgError) {
    return (
      <span
        className={[containerCls, styles.fallback].filter(Boolean).join(' ')}
        style={customStyle}
        role="img"
        aria-label={alt || undefined}
      >
        {fallbackText}
      </span>
    )
  }

  return (
    <img
      src={src}
      alt={alt}
      className={containerCls}
      style={customStyle}
      onError={handleError}
      decoding="async"
    />
  )
}

export { Avatar }
export type { AvatarProps, AvatarSize, AvatarShape }
