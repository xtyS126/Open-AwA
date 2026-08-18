/**
 * PetOverlayApp —— 宠物悬浮窗独立 React 入口
 *
 * 仅在桌面端宠物悬浮窗 BrowserWindow 中使用（通过 window.__OPENAWA_PET_OVERLAY__ 检测）。
 * 轻量渲染，无导航栏/侧边栏，纯宠物展示。
 *
 * 功能：
 * - 从主进程获取宠物配置与后端 URL
 * - 从后端拉取激活宠物数据并渲染 PetSprite
 * - 读取当前激活角色的 live2d_model_id，若绑定则渲染 Live2DViewer
 * - 监听 IPC 事件（动画/表情），更新宠物状态
 * - 点击宠物时通知主窗口唤起主窗口
 * - 支持右键菜单（隐藏/切换宠物/退出）
 * - 定期轮询角色切换事件，自动更新渲染
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { Navigate } from '@/shared/routing'
import type { PetResponse } from '@/features/pets/types'
import type { Live2DModelResponse } from '@/shared/api/live2dApi'

/** 宠物悬浮窗 preload 注入的 API 类型 */
interface PetOverlayApi {
  getConfig: () => Promise<PetOverlayConfig>
  onAnimation: (callback: (data: { eventType: string; payload?: Record<string, unknown> }) => void) => () => void
  onExpression: (callback: (expression: string) => void) => () => void
  notifyClicked: () => void
  ipc: {
    invoke: (channel: string, ...args: unknown[]) => Promise<unknown>
  }
}

/** 主进程返回的宠物配置 */
interface PetOverlayConfig {
  enabled: boolean
  petId: string
  position: { x: number; y: number }
  size: number
  alwaysOnTop: boolean
}

/** 后端 assistant_context 响应 */
interface AssistantContextResponse {
  session_id: string
  role_id: string | null
  workspace_id: string
  selected_memory_ids: number[]
  speaker_id: string | null
}

/** 角色详情响应（含 live2d_model_id） */
interface RoleDetailResponse {
  id: string
  name: string
  live2d_model_id: string | null
  avatar_url: string
}

/** 右键菜单状态 */
interface ContextMenuState {
  visible: boolean
  x: number
  y: number
}

/** 宠物事件类型到动画名称的映射（悬浮窗用） */
const OVERLAY_EVENT_ANIMATION_MAP: Record<string, string> = {
  'chat:user-message': 'listen',
  'chat:ai-thinking': 'think',
  'chat:ai-reply': 'talk',
  'chat:positive': 'happy',
  'chat:negative': 'worry',
  'companion:bond-upgrade': 'celebrate',
  'companion:milestone': 'special',
}

/** 获取宠物悬浮窗 API（浏览器环境安全检测） */
function getPetOverlayApi(): PetOverlayApi | null {
  if (typeof window === 'undefined') return null
  return (window as unknown as Record<string, unknown>).__OPENAWA_PET_OVERLAY__ as PetOverlayApi | null
}

export default function PetOverlayApp() {
  const api = getPetOverlayApi()

  // 非桌面端宠物悬浮窗环境：重定向到助手页
  if (!api) {
    return <Navigate to="/assistant" replace />
  }

  return <PetOverlayContent api={api} />
}

/** 宠物悬浮窗核心内容组件 */
function PetOverlayContent({ api }: { api: PetOverlayApi }) {
  const [pet, setPet] = useState<PetResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [animationName, setAnimationName] = useState('idle')
  const [backendUrl, setBackendUrl] = useState('')
  const [menu, setMenu] = useState<ContextMenuState>({ visible: false, x: 0, y: 0 })
  const cleanupRef = useRef<Array<() => void>>([])
  // 角色 Live2D 模型绑定
  const [live2dModelId, setLive2dModelId] = useState<string | null>(null)
  const [_roleName, setRoleName] = useState<string | null>(null)
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // 初始化：获取宠物配置与后端 URL
  useEffect(() => {
    let cancelled = false

    async function init() {
      try {
        // 获取后端 URL
        let url = ''
        try {
          const result = await api.ipc.invoke('backend:get-url')
          url = (result as string) || ''
        } catch {
          // 后端 URL 获取失败，使用空字符串（dev 模式下走 Vite proxy）
        }
        if (cancelled) return
        setBackendUrl(url)

        // 获取宠物配置
        const config = await api.getConfig()
        if (cancelled) return

        if (!config.petId) {
          setLoading(false)
          return
        }

        // 从后端拉取激活宠物数据
        await fetchPetData(config.petId, url)
      } catch (err) {
        if (!cancelled) {
          setError('宠物数据加载失败')
          setLoading(false)
        }
      }
    }

    async function fetchPetData(petId: string, baseUrl: string) {
      try {
        // 获取宠物列表并找到激活的宠物
        const listUrl = baseUrl ? `${baseUrl}/api/pets` : '/api/pets'
        const listRes = await fetch(listUrl)
        if (!listRes.ok) throw new Error(`HTTP ${listRes.status}`)
        const listData = await listRes.json()
        const pets: PetResponse[] = listData.pets || []
        const activePet = pets.find((p) => p.pet_id === petId && p.is_active)
        if (cancelled) return
        if (activePet) {
          setPet(activePet)
        } else {
          setError('未找到激活的宠物')
        }
      } catch (err) {
        if (!cancelled) {
          setError('宠物数据加载失败')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    init()
    return () => {
      cancelled = true
    }
  }, [api])

  // 监听 IPC 动画事件（主窗口通过 IPC 转发到悬浮窗）
  useEffect(() => {
    const unsub = api.onAnimation((data: { eventType: string; payload?: Record<string, unknown> }) => {
      const mapped = OVERLAY_EVENT_ANIMATION_MAP[data.eventType]
      if (mapped) {
        setAnimationName(mapped)
      }
    })
    cleanupRef.current.push(unsub)
    return () => {
      unsub()
    }
  }, [api])

  // 监听 IPC 表情事件（表情名映射为动画名）
  useEffect(() => {
    const unsub = api.onExpression((expression: string) => {
      // 表情名直接作为动画名使用
      setAnimationName(expression)
    })
    cleanupRef.current.push(unsub)
    return () => {
      unsub()
    }
  }, [api])

  // 轮询当前激活角色的 Live2D 模型绑定（每 10 秒检查一次）
  useEffect(() => {
    const baseUrl = backendUrl || ''

    const checkActiveRoleLive2D = async () => {
      try {
        // 获取最近会话列表
        const convUrl = baseUrl ? `${baseUrl}/api/conversations?page_size=1` : '/api/conversations?page_size=1'
        const convRes = await fetch(convUrl)
        if (!convRes.ok) return
        const convData = await convRes.json()
        const sessions = convData.items || []
        if (sessions.length === 0) {
          setLive2dModelId(null)
          setRoleName(null)
          return
        }

        const sessionId = sessions[0].session_id
        if (!sessionId) return

        // 获取 assistant_context
        const ctxUrl = baseUrl
          ? `${baseUrl}/api/conversations/${encodeURIComponent(sessionId)}/assistant-context`
          : `/api/conversations/${encodeURIComponent(sessionId)}/assistant-context`
        const ctxRes = await fetch(ctxUrl)
        if (!ctxRes.ok) return
        const ctxData: AssistantContextResponse = await ctxRes.json()
        if (!ctxData.role_id) {
          setLive2dModelId(null)
          setRoleName(null)
          return
        }

        // 获取角色详情
        const roleUrl = baseUrl
          ? `${baseUrl}/api/roles/${encodeURIComponent(ctxData.role_id)}`
          : `/api/roles/${encodeURIComponent(ctxData.role_id)}`
        const roleRes = await fetch(roleUrl)
        if (!roleRes.ok) return
        const roleData: RoleDetailResponse = await roleRes.json()
        if (roleData.live2d_model_id) {
          setLive2dModelId(roleData.live2d_model_id)
          setRoleName(roleData.name)
        } else {
          setLive2dModelId(null)
          setRoleName(null)
        }
      } catch {
        // 轮询失败静默，不影响宠物精灵渲染
      }
    }

    // 首次检查
    if (backendUrl !== undefined) {
      void checkActiveRoleLive2D()
    }

    // 定期轮询
    pollTimerRef.current = setInterval(() => {
      void checkActiveRoleLive2D()
    }, 10_000)

    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
  }, [backendUrl])

  // 点击宠物：通知主窗口
  const handleClick = useCallback(() => {
    api.notifyClicked()
    // 关闭右键菜单
    setMenu({ visible: false, x: 0, y: 0 })
  }, [api])

  // 右键菜单
  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setMenu({ visible: true, x: e.clientX, y: e.clientY })
  }, [])

  // 关闭右键菜单
  const closeMenu = useCallback(() => {
    setMenu({ visible: false, x: 0, y: 0 })
  }, [])

  // 隐藏悬浮窗
  const handleHide = useCallback(() => {
    api.ipc.invoke('pet:hide').catch(() => {})
    closeMenu()
  }, [api, closeMenu])

  // 切换宠物（通知主窗口打开宠物设置）
  const handleSwitchPet = useCallback(() => {
    api.notifyClicked()
    closeMenu()
  }, [api, closeMenu])

  // 点击外部关闭菜单
  useEffect(() => {
    if (!menu.visible) return
    const handler = () => closeMenu()
    window.addEventListener('click', handler)
    return () => window.removeEventListener('click', handler)
  }, [menu.visible, closeMenu])

  // 加载中
  if (loading) {
    return (
      <div style={overlayContainerStyle}>
        <div style={statusTextStyle}>加载中...</div>
      </div>
    )
  }

  // 错误状态
  if (error) {
    return (
      <div style={overlayContainerStyle}>
        <div style={statusTextStyle}>{error}</div>
      </div>
    )
  }

  // 无宠物且无 Live2D 角色
  if (!pet && !live2dModelId) {
    return (
      <div style={overlayContainerStyle}>
        <div style={statusTextStyle}>未启用宠物</div>
      </div>
    )
  }

  return (
    <div
      style={overlayContainerStyle}
      onClick={handleClick}
      onContextMenu={handleContextMenu}
    >
      {/* 角色 Live2D 模型渲染（优先于宠物精灵） */}
      {live2dModelId ? (
        <Live2DOverlayWrapper modelId={live2dModelId} backendUrl={backendUrl} />
      ) : pet ? (
        <PetSpriteWrapper pet={pet} animationName={animationName} backendUrl={backendUrl} />
      ) : null}

      {/* 右键菜单 */}
      {menu.visible && (
        <div style={{
          ...contextMenuStyle,
          left: menu.x,
          top: menu.y,
        }}>
          <div style={menuItemStyle} onClick={handleSwitchPet}>
            切换宠物
          </div>
          <div style={menuItemStyle} onClick={handleHide}>
            隐藏
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * 宠物精灵渲染包装器
 * 使用 Canvas 直接绘制精灵表，避免引入完整的 PetSprite 组件依赖链
 */
function PetSpriteWrapper({
  pet,
  animationName,
  backendUrl,
}: {
  pet: PetResponse
  animationName: string
  backendUrl: string
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)
  const rafRef = useRef<number>(0)
  const [imgStatus, setImgStatus] = useState<'loading' | 'ready' | 'error'>('loading')

  const { frame_width: fw, frame_height: fh, columns, animations } = pet
  const scale = 1.5

  // 加载精灵表图片
  useEffect(() => {
    let cancelled = false
    setImgStatus('loading')

    const spriteUrl = backendUrl
      ? `${backendUrl}/api/pets/${encodeURIComponent(pet.id)}/spritesheet`
      : `/api/pets/${encodeURIComponent(pet.id)}/spritesheet`

    const img = new Image()
    img.onload = () => {
      if (!cancelled) {
        imageRef.current = img
        setImgStatus('ready')
      }
    }
    img.onerror = () => {
      if (!cancelled) {
        setImgStatus('error')
      }
    }
    img.src = spriteUrl
    return () => {
      cancelled = true
      img.onload = null
      img.onerror = null
    }
  }, [pet.id, backendUrl])

  // 主绘制与动画循环
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || imgStatus !== 'ready') return

    const img = imageRef.current
    if (!img) return

    const w = Math.max(1, Math.round(fw * scale))
    const h = Math.max(1, Math.round(fh * scale))
    canvas.width = w
    canvas.height = h

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.imageSmoothingEnabled = false

    const animation = animations[animationName] || Object.values(animations)[0]
    if (!animation || animation.frames.length === 0) return

    const frames = animation.frames
    const lastFrameIndex = frames.length - 1
    const loopStart = animation.loop_start

    const drawFrame = (idx: number) => {
      const frame = frames[idx]
      if (!frame) return
      const row = Math.floor(frame.sprite_index / columns)
      const col = frame.sprite_index % columns
      ctx.clearRect(0, 0, w, h)
      try {
        ctx.drawImage(img, col * fw, row * fh, fw, fh, 0, 0, w, h)
      } catch {
        // 图片未解码完成，下一帧重试
      }
    }

    drawFrame(0)

    // 单帧动画：仅展示首帧
    if (frames.length <= 1) return

    let frameIndex = 0
    let accumulated = 0
    let lastTs: number | null = null
    let finished = false

    const tick = (ts: number) => {
      if (finished) return
      if (lastTs == null) lastTs = ts
      const delta = ts - lastTs
      lastTs = ts
      accumulated += delta
      const current = frames[frameIndex]
      const dur = current.duration_ms > 0 ? current.duration_ms : 100
      if (accumulated >= dur) {
        accumulated -= dur
        const isLast = frameIndex === lastFrameIndex
        if (isLast && loopStart == null) {
          finished = true
          drawFrame(lastFrameIndex)
          return
        }
        frameIndex = isLast ? (loopStart ?? 0) : frameIndex + 1
        drawFrame(frameIndex)
      }
      rafRef.current = requestAnimationFrame(tick)
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [pet.id, fw, fh, columns, animations, animationName, scale, imgStatus])

  return (
    <canvas
      ref={canvasRef}
      style={{
        imageRendering: 'pixelated',
        display: 'block',
        cursor: 'pointer',
      }}
      aria-label={pet.display_name}
      role="img"
    />
  )
}

// ---- 样式常量 ----

const overlayContainerStyle: React.CSSProperties = {
  width: '100%',
  height: '100%',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  overflow: 'hidden',
  userSelect: 'none',
  WebkitUserSelect: 'none',
  background: 'transparent',
  // 允许点击穿透透明区域（由 Electron 窗口透明属性配合）
  pointerEvents: 'auto',
}

const statusTextStyle: React.CSSProperties = {
  color: 'rgba(255, 255, 255, 0.7)',
  fontSize: '12px',
  textAlign: 'center',
  padding: '8px',
  borderRadius: '4px',
  background: 'rgba(0, 0, 0, 0.4)',
}

const contextMenuStyle: React.CSSProperties = {
  position: 'fixed',
  background: 'rgba(30, 30, 30, 0.95)',
  borderRadius: '6px',
  padding: '4px 0',
  minWidth: '100px',
  boxShadow: '0 4px 12px rgba(0, 0, 0, 0.5)',
  zIndex: 9999,
  backdropFilter: 'blur(10px)',
}

const menuItemStyle: React.CSSProperties = {
  padding: '6px 16px',
  fontSize: '12px',
  color: 'rgba(255, 255, 255, 0.9)',
  cursor: 'pointer',
  whiteSpace: 'nowrap',
  transition: 'background 0.15s',
}

/**
 * Live2D 模型悬浮窗渲染包装器
 * 使用原生 fetch 获取模型元数据，渲染简化的 Live2D 占位视图
 */
function Live2DOverlayWrapper({
  modelId,
  backendUrl,
}: {
  modelId: string
  backendUrl: string
}) {
  const [modelName, setModelName] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    const fetchModel = async () => {
      try {
        // 获取模型列表并找到目标模型
        const listUrl = backendUrl
          ? `${backendUrl}/api/pets/live2d/models`
          : '/api/pets/live2d/models'
        const listRes = await fetch(listUrl)
        if (!listRes.ok) throw new Error('模型列表加载失败')
        const listData = await listRes.json()
        const models: Live2DModelResponse[] = listData.models || []
        const model = models.find((m) => m.id === modelId)
        if (cancelled) return
        if (model) {
          setModelName(model.model_name)
          // 尝试获取第一个纹理作为预览
          if (model.texture_paths && model.texture_paths.length > 0) {
            const texUrl = backendUrl
              ? `${backendUrl}/api/pets/live2d/${encodeURIComponent(modelId)}/files/${encodeURIComponent(model.texture_paths[0])}`
              : `/api/pets/live2d/${encodeURIComponent(modelId)}/files/${encodeURIComponent(model.texture_paths[0])}`
            setPreviewUrl(texUrl)
          }
        } else {
          setLoadError('模型不存在')
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : '加载失败')
        }
      }
    }

    void fetchModel()
    return () => {
      cancelled = true
    }
  }, [modelId, backendUrl])

  if (loadError) {
    return (
      <div style={{ textAlign: 'center' }}>
        <div style={statusTextStyle}>{loadError}</div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
      {previewUrl ? (
        <img
          src={previewUrl}
          alt={modelName || 'Live2D'}
          style={{
            maxWidth: '120px',
            maxHeight: '160px',
            objectFit: 'contain',
            imageRendering: 'auto',
          }}
        />
      ) : (
        <div style={{
          width: '100px',
          height: '120px',
          borderRadius: '8px',
          background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.3), rgba(139, 92, 246, 0.3))',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          border: '2px solid rgba(99, 102, 241, 0.5)',
        }}>
          <span style={{ color: 'rgba(255,255,255,0.7)', fontSize: '11px' }}>
            {modelName || 'Live2D'}
          </span>
        </div>
      )}
      {modelName && (
        <span style={{ color: 'rgba(255,255,255,0.6)', fontSize: '10px' }}>
          {modelName}
        </span>
      )}
    </div>
  )
}