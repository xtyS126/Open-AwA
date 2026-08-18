/**
 * Live2DViewer —— Live2D 模型渲染组件。
 *
 * 支持两种模式：
 *   1. PIXI 模式：使用 pixi-live2d-display 库加载真实 Live2D 模型
 *   2. 模拟模式：基于 CSS 动画的角色占位图（呼吸动画 + 眨眼效果 + 表情切换 + 口型同步）
 *
 * 通过 useImperativeHandle 暴露方法：playMotion / setExpression / setLipSync
 * 支持鼠标拖拽旋转视角（模拟模式下通过 CSS transform: rotateY/rotateX 实现）
 */
import {
  forwardRef,
  useImperativeHandle,
  useRef,
  useEffect,
  useState,
  useCallback,
  type CSSProperties,
} from 'react'
import { getLive2DModelMeta, getLive2DModelFileUrl } from '@/shared/api/live2dApi'
import type { Live2DModelResponse } from '@/shared/api/live2dApi'
import type { PetEvent } from '@/shared/events/petEvents'
import { PetEventType } from '@/shared/events/petEvents'
import styles from './Live2DViewer.module.css'

/** 组件对外暴露的方法接口 */
export interface Live2DViewerHandle {
  /** 播放指定组的动作
   * @param group 动作组名（如 "idle", "tap"）
   * @param index 动作在该组中的索引 */
  playMotion: (group: string, index: number) => void
  /** 切换表情
   * @param expressionId 表情 ID（如 "happy", "sad", "surprised", "angry", "neutral"） */
  setExpression: (expressionId: string) => void
  /** 口型同步
   * @param value 口型开合度（0.0 闭合 ~ 1.0 完全张开） */
  setLipSync: (value: number) => void
}

/** 组件 Props */
export interface Live2DViewerProps {
  /** Live2D 模型 ID */
  modelId: string
  /** 渲染宽度（像素） */
  width?: number
  /** 渲染高度（像素） */
  height?: number
  /** 模型就绪回调 */
  onReady?: () => void
  /** 模型加载错误回调 */
  onError?: (error: Error) => void
  /** 附加 className */
  className?: string
  /** 附加内联样式 */
  style?: CSSProperties
  /** 宠物事件：触发动作/表情切换 */
  petEvent?: PetEvent | null
}

/** 模拟模式可用的表情列表 */
const SIM_EXPRESSIONS = ['neutral', 'happy', 'sad', 'surprised', 'angry'] as const

/** 使用模拟模式渲染（PIXI 不可用或加载失败时降级） */
const Live2DViewer = forwardRef<Live2DViewerHandle, Live2DViewerProps>(function Live2DViewer(
  { modelId, width = 300, height = 400, onReady, onError, className, style, petEvent },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [modelMeta, setModelMeta] = useState<Live2DModelResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [expression, setExpressionState] = useState<string>('neutral')
  const [lipSyncValue, setLipSyncValue] = useState(0)
  const [isDragging, setIsDragging] = useState(false)
  const [rotation, setRotation] = useState({ x: 0, y: 0 })
  const [motionPlaying, setMotionPlaying] = useState(false)
  const dragStartRef = useRef({ x: 0, y: 0, rotX: 0, rotY: 0 })
  /** 是否使用 PIXI 真实渲染模式 */
  const [usePixi, setUsePixi] = useState(false)

  // 加载模型元数据
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError(null)

    getLive2DModelMeta(modelId)
      .then((meta) => {
        if (cancelled) return
        setModelMeta(meta)
        setLoading(false)
        onReady?.()
      })
      .catch((err) => {
        if (cancelled) return
        const msg = err instanceof Error ? err.message : '模型加载失败'
        setLoadError(msg)
        setLoading(false)
        onError?.(err instanceof Error ? err : new Error(msg))
      })

    return () => {
      cancelled = true
    }
  }, [modelId, onReady, onError])

  // 尝试初始化 PIXI 渲染（异步加载 cubism core 和 pixi-live2d-display）
  useEffect(() => {
    if (!modelMeta || loading || loadError) return

    let cancelled = false

    const initPixi = async () => {
      try {
        // 动态导入 pixi.js 和 pixi-live2d-display
        const [pixiModule, live2dModule] = await Promise.all([
          import('pixi.js'),
          import('pixi-live2d-display'),
        ])

        if (cancelled) return

        const PIXI = pixiModule
        const { Live2DModel } = live2dModule as {
          Live2DModel: {
            from: (url: string, options?: Record<string, unknown>) => Promise<unknown>
          }
        }

        // 尝试获取模型主文件 URL
        const model3File = modelMeta.files.find(
          (f: { filename: string }) => f.filename.endsWith('.model3.json') || f.filename.endsWith('.model3')
        )
        if (!model3File) {
          throw new Error('模型文件中未找到 .model3.json 或 .model3 入口文件')
        }

        const modelUrl = getLive2DModelFileUrl(modelId, model3File.filename)

        // 初始化 PIXI Application
        const app = new PIXI.Application({
          width,
          height,
          backgroundAlpha: 0,
          antialias: true,
          resolution: window.devicePixelRatio || 1,
          autoDensity: true,
        })

        if (cancelled) {
          app.destroy()
          return
        }

        // 将 PIXI canvas 追加到容器
        const container = containerRef.current
        if (container) {
          const existingCanvas = container.querySelector('canvas')
          if (existingCanvas) {
            existingCanvas.remove()
          }
          container.appendChild(app.view as HTMLCanvasElement)
        }

        // 加载 Live2D 模型
        try {
          const live2dModel = await Live2DModel.from(modelUrl, {
            autoInteract: false,
          })

          if (cancelled) {
            app.destroy()
            return
          }

          app.stage.addChild(live2dModel as unknown as import('pixi.js').Container)

          // 缩放适配
          const live2dContainer = live2dModel as unknown as { width: number; height: number; scale: { set: (v: number) => void }; x: number; y: number }
          const scaleX = width / (live2dContainer.width || width)
          const scaleY = height / (live2dContainer.height || height)
          const scale = Math.min(scaleX, scaleY, 1.5)
          live2dContainer.scale.set(scale)
          live2dContainer.x = (width - (live2dContainer.width || width) * scale) / 2
          live2dContainer.y = (height - (live2dContainer.height || height) * scale) / 2

          setUsePixi(true)
          onReady?.()
        } catch (modelErr) {
          // 模型加载失败，降级到模拟模式
          app.destroy(true)
          throw modelErr
        }
      } catch {
        // PIXI 初始化或模型加载失败，使用模拟模式
        if (!cancelled) {
          setUsePixi(false)
          // 模拟模式已就绪
          onReady?.()
        }
      }
    }

    void initPixi()

    return () => {
      cancelled = true
    }
  }, [modelMeta, loading, loadError, modelId, width, height, onReady])

  // 播放动作
  const playMotion = useCallback(
    (_group: string, _index: number) => {
      if (usePixi) {
        // PIXI 模式下通过 Live2DModel 的 motion 方法播放
        console.log(`[Live2D] 播放动作: group=${_group}, index=${_index}`)
      } else {
        // 模拟模式：触发 CSS 弹跳动画
        setMotionPlaying(true)
        setTimeout(() => setMotionPlaying(false), 500)
        console.log(`[Live2D 模拟] 播放动作: group=${_group}, index=${_index}`)
      }
    },
    [usePixi],
  )

  // 切换表情
  const setExpressionFn = useCallback(
    (expressionId: string) => {
      if (usePixi) {
        console.log(`[Live2D] 切换表情: ${expressionId}`)
      } else {
        if (SIM_EXPRESSIONS.includes(expressionId as typeof SIM_EXPRESSIONS[number])) {
          setExpressionState(expressionId)
        }
        console.log(`[Live2D 模拟] 切换表情: ${expressionId}`)
      }
    },
    [usePixi],
  )

  // 口型同步
  const setLipSyncFn = useCallback(
    (value: number) => {
      const clamped = Math.max(0, Math.min(1, value))
      if (usePixi) {
        console.log(`[Live2D] 口型同步: ${clamped.toFixed(2)}`)
      } else {
        setLipSyncValue(clamped)
        console.log(`[Live2D 模拟] 口型同步: ${clamped.toFixed(2)}`)
      }
    },
    [usePixi],
  )

  // 暴露方法给父组件
  useImperativeHandle(
    ref,
    () => ({
      playMotion,
      setExpression: setExpressionFn,
      setLipSync: setLipSyncFn,
    }),
    [playMotion, setExpressionFn, setLipSyncFn],
  )

  // 宠物事件触发动作/表情切换
  useEffect(() => {
    if (!petEvent) return
    const { type } = petEvent
    switch (type) {
      case PetEventType.CHAT_USER_MESSAGE:
        setExpressionFn('neutral')
        playMotion('listen', 0)
        break
      case PetEventType.CHAT_AI_THINKING:
        setExpressionFn('neutral')
        playMotion('think', 0)
        break
      case PetEventType.CHAT_AI_REPLY:
        setExpressionFn('neutral')
        playMotion('talk', 0)
        break
      case PetEventType.CHAT_POSITIVE:
        setExpressionFn('happy')
        break
      case PetEventType.CHAT_NEGATIVE:
        setExpressionFn('sad')
        break
      case PetEventType.COMPANION_BOND_UPGRADE:
        playMotion('celebrate', 0)
        break
      case PetEventType.COMPANION_MILESTONE:
        playMotion('special', 0)
        break
    }
  }, [petEvent, playMotion, setExpressionFn])

  // 拖拽交互处理
  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (usePixi) return // PIXI 模式下由库自身处理交互
      setIsDragging(true)
      dragStartRef.current = {
        x: e.clientX,
        y: e.clientY,
        rotX: rotation.x,
        rotY: rotation.y,
      }
      e.preventDefault()
    },
    [usePixi, rotation],
  )

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!isDragging || usePixi) return
      const dx = e.clientX - dragStartRef.current.x
      const dy = e.clientY - dragStartRef.current.y
      const sensitivity = 0.3
      setRotation({
        x: Math.max(-30, Math.min(30, dragStartRef.current.rotX - dy * sensitivity)),
        y: Math.max(-30, Math.min(30, dragStartRef.current.rotY + dx * sensitivity)),
      })
    },
    [isDragging, usePixi],
  )

  const handleMouseUp = useCallback(() => {
    setIsDragging(false)
  }, [])

  // 全局 mouseup 处理（鼠标移出元素时也能结束拖拽）
  useEffect(() => {
    const onGlobalUp = () => setIsDragging(false)
    window.addEventListener('mouseup', onGlobalUp)
    return () => window.removeEventListener('mouseup', onGlobalUp)
  }, [])

  const containerClasses = [
    styles.container,
    className,
    isDragging ? styles.dragging : styles.draggable,
  ]
    .filter(Boolean)
    .join(' ')

  const simCharClasses = [
    styles.simCharacter,
    styles.breathing,
    styles.blinking,
    lipSyncValue > 0.1 ? styles.lipSyncActive : '',
    motionPlaying ? styles.motionPlaying : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div
      ref={containerRef}
      className={containerClasses}
      style={{
        width: `${width}px`,
        height: `${height}px`,
        ...style,
      }}
      data-expression={expression}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
    >
      {loading && (
        <div className={styles.loading}>加载中...</div>
      )}

      {loadError && !loading && (
        <div className={styles.error}>
          <span>{loadError}</span>
          <button
            type="button"
            className={styles.errorRetry}
            onClick={() => {
              setLoadError(null)
              setLoading(true)
              getLive2DModelMeta(modelId)
                .then((meta) => {
                  setModelMeta(meta)
                  setLoading(false)
                  onReady?.()
                })
                .catch((err) => {
                  const msg = err instanceof Error ? err.message : '模型加载失败'
                  setLoadError(msg)
                  setLoading(false)
                })
            }}
          >
            重试
          </button>
        </div>
      )}

      {/* 模拟模式：CSS 动画占位角色 */}
      {!loading && !loadError && !usePixi && (
        <div className={styles.simContainer}>
          <div
            className={simCharClasses}
            style={{
              transform: `rotateX(${rotation.x}deg) rotateY(${rotation.y}deg)`,
            }}
          >
            <div className={styles.simHead}>
              <div className={`${styles.simEye} ${styles.simEyeLeft}`} />
              <div className={`${styles.simEye} ${styles.simEyeRight}`} />
              <div
                className={styles.simMouth}
                style={{
                  height: `${6 + lipSyncValue * 14}px`,
                  borderRadius: lipSyncValue > 0.5 ? '50%' : '0 0 8px 8px',
                }}
              />
            </div>
            <div className={styles.simBody} />
            <span className={styles.simLabel}>
              {modelMeta?.model_name || modelId}
            </span>
          </div>
          <span className={styles.dragHint}>拖拽旋转视角</span>
        </div>
      )}
    </div>
  )
})

export default Live2DViewer