/**
 * PetSprite —— 宠物精灵表（spritesheet）动画渲染器。
 *
 * 基于 Canvas 按帧切片绘制精灵表，使用 requestAnimationFrame 推进逐帧动画：
 *   - 帧定位：row = floor(sprite_index / columns)，col = sprite_index % columns
 *   - 循环语义：loop_start 非 null 时播完末帧跳回 loop_start；为 null 时播完停在末帧
 *   - prefers-reduced-motion 偏好下仅绘制首帧，不进入帧循环
 *   - 资源切换（pet / animationName / 缩放）与卸载时自动清理旧 rAF
 *   - 精灵表未就绪或加载失败时显示占位文案
 */
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { getPetSpritesheetUrl } from './petsApi'
import type { PetResponse, PetAnimationFrame } from './types'
import { useMediaQuery } from '@/shared/hooks/useMediaQuery'

interface PetSpriteProps {
  /** 宠物信息 */
  pet: PetResponse
  /** 动画名称，默认 'idle' */
  animationName?: string
  /** 是否播放，默认 true；为 false 时停留在当前帧，恢复后继续 */
  playing?: boolean
  /** 缩放倍数，默认 1（canvas 像素尺寸 = frame_size * scale） */
  scale?: number
  /** 附加 className */
  className?: string
  /** 附加内联样式 */
  style?: CSSProperties
}

type ImageStatus = 'loading' | 'ready' | 'error'

export default function PetSprite({
  pet,
  animationName = 'idle',
  playing = true,
  scale = 1,
  className,
  style,
}: PetSpriteProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  /** 已加载的精灵表图片实例，跨渲染复用，仅由图片加载流程写入 */
  const imageRef = useRef<HTMLImageElement | null>(null)
  /** playing 的实时引用：避免动画 effect 依赖 playing 而随暂停/恢复频繁重启 */
  const playingRef = useRef(playing)
  const prefersReducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)')
  const [imageStatus, setImageStatus] = useState<ImageStatus>('loading')

  // 字段容错：精灵表未就绪或缺少关键尺寸时无法切片绘制
  const canDraw =
    pet.spritesheet_ready &&
    pet.frame_width > 0 &&
    pet.frame_height > 0 &&
    pet.columns > 0 &&
    Object.keys(pet.animations || {}).length > 0

  // 同步 playingRef，动画循环内读取该引用实现暂停/恢复
  useEffect(() => {
    playingRef.current = playing
  }, [playing])

  // 精灵表图片加载：仅与宠物身份相关，避免动画切换重复下载
  useEffect(() => {
    if (!canDraw) {
      setImageStatus('loading')
      imageRef.current = null
      return
    }
    let cancelled = false
    setImageStatus('loading')
    const img = new Image()
    img.onload = () => {
      if (!cancelled) {
        imageRef.current = img
        setImageStatus('ready')
      }
    }
    img.onerror = () => {
      if (!cancelled) {
        imageRef.current = null
        setImageStatus('error')
      }
    }
    img.src = getPetSpritesheetUrl(pet.id)
    return () => {
      cancelled = true
      img.onload = null
      img.onerror = null
    }
  }, [canDraw, pet.id])

  // 主绘制与动画循环：资源就绪后逐帧推进
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const fw = pet.frame_width
    const fh = pet.frame_height
    const columns = pet.columns
    const w = Math.max(1, Math.round(fw * scale))
    const h = Math.max(1, Math.round(fh * scale))
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, w, h)

    // 未就绪或不可绘制时不启动动画
    if (!canDraw || imageStatus !== 'ready') {
      return
    }

    const img = imageRef.current
    if (!img) return

    // 解析目标动画：找不到指定动画时回退到首个可用动画
    const animations = pet.animations || {}
    const animation =
      animations[animationName] || Object.values(animations)[0] || null
    if (!animation || animation.frames.length === 0) return

    const frames: PetAnimationFrame[] = animation.frames
    const lastFrameIndex = frames.length - 1
    const loopStart = animation.loop_start
    const multiFrame = frames.length > 1

    ctx.imageSmoothingEnabled = false

    // 单帧切片绘制：依据 sprite_index 计算行列，从精灵表裁剪到 canvas
    const drawFrame = (idx: number) => {
      const frame = frames[idx]
      if (!frame) return
      const row = Math.floor(frame.sprite_index / columns)
      const col = frame.sprite_index % columns
      ctx.clearRect(0, 0, w, h)
      try {
        ctx.drawImage(
          img,
          col * fw, row * fh, fw, fh,
          0, 0, w, h,
        )
      } catch {
        // 图片尚未解码完整时忽略本次绘制，下一帧重试
      }
    }

    drawFrame(0)

    // 单帧动画或开启 reduced-motion 偏好：仅展示首帧，不进入帧循环
    if (!multiFrame || prefersReducedMotion) {
      return
    }

    let frameIndex = 0
    let accumulated = 0
    let lastTs: number | null = null
    // finished：loop_start 为 null 的单次动画播完末帧后停止循环链
    let finished = false
    let rafId = 0

    const tick = (ts: number) => {
      if (finished) return
      if (lastTs == null) lastTs = ts
      const delta = ts - lastTs
      lastTs = ts
      if (playingRef.current) {
        accumulated += delta
        const current = frames[frameIndex]
        const dur = current.duration_ms > 0 ? current.duration_ms : 100
        if (accumulated >= dur) {
          accumulated -= dur
          const isLast = frameIndex === lastFrameIndex
          if (isLast && loopStart == null) {
            // 播完停在末帧
            finished = true
            drawFrame(lastFrameIndex)
            return
          }
          frameIndex = isLast ? (loopStart ?? 0) : frameIndex + 1
          drawFrame(frameIndex)
        }
      }
      rafId = requestAnimationFrame(tick)
    }

    rafId = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canDraw, imageStatus, pet.id, pet.frame_width, pet.frame_height, pet.columns, pet.animations, animationName, scale, prefersReducedMotion])

  const showOverlay = !canDraw || imageStatus !== 'ready'
  const overlayText = !canDraw
    ? '暂无精灵表'
    : imageStatus === 'loading'
      ? '加载中...'
      : imageStatus === 'error'
        ? '加载失败'
        : ''

  return (
    <span className={className} style={{ position: 'relative', display: 'inline-block', lineHeight: 0, ...style }}>
      <canvas
        ref={canvasRef}
        style={{ imageRendering: 'pixelated', display: 'block' }}
        aria-label={pet.display_name}
        role="img"
      />
      {showOverlay && (
        <span
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 'var(--text-xs, 12px)',
            color: 'var(--color-text-tertiary)',
            background: 'var(--color-bg-tertiary)',
            borderRadius: 'var(--radius-sm, 6px)',
            lineHeight: 1.2,
            textAlign: 'center',
            padding: '4px',
            boxSizing: 'border-box',
          }}
        >
          {overlayText}
        </span>
      )}
    </span>
  )
}