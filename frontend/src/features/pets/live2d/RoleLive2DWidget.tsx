/**
 * RoleLive2DWidget —— 根据当前会话激活角色渲染 Live2D 模型或角色头像。
 *
 * 读取当前会话的 assistant_context 获取 role_id，再查询角色详情获取 live2d_model_id：
 *   - 已绑定 Live2D 模型：渲染 Live2DViewer 组件
 *   - 未绑定：渲染角色头像占位
 *   - 无激活角色：显示"未选择角色"提示
 *   - 角色切换时自动跟随更新
 */
import { useEffect, useState, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { conversationAPI } from '@/shared/api/conversationApi'
import { getRole } from '@/shared/api/rolesApi'
import Live2DViewer from './Live2DViewer'
import type { AgentRole } from '@/shared/types/role'
import styles from './RoleLive2DWidget.module.css'

export interface RoleLive2DWidgetProps {
  /** 当前会话 ID */
  sessionId: string
  /** 渲染宽度 */
  width?: number
  /** 渲染高度 */
  height?: number
  /** 附加 className */
  className?: string
}

export default function RoleLive2DWidget({
  sessionId,
  width = 200,
  height = 280,
  className,
}: RoleLive2DWidgetProps) {
  const [role, setRole] = useState<AgentRole | null>(null)
  const prevRoleIdRef = useRef<string | null>(null)

  // 查询当前会话的 assistant_context，获取 role_id
  const contextQuery = useQuery({
    queryKey: ['conversations', sessionId, 'assistant-context'],
    queryFn: async () => {
      const { data } = await conversationAPI.getAssistantContext(sessionId)
      return data
    },
    enabled: Boolean(sessionId && sessionId !== 'default'),
    staleTime: 30_000,
  })

  const activeRoleId = contextQuery.data?.role_id || null

  // 当 role_id 变化时，重新加载角色详情
  useEffect(() => {
    if (!activeRoleId) {
      setRole(null)
      prevRoleIdRef.current = null
      return
    }

    // 角色未变化，跳过重复加载
    if (activeRoleId === prevRoleIdRef.current) return
    prevRoleIdRef.current = activeRoleId

    let cancelled = false
    getRole(activeRoleId)
      .then((roleData) => {
        if (cancelled) return
        setRole(roleData)
      })
      .catch(() => {
        if (cancelled) return
        setRole(null)
      })

    return () => {
      cancelled = true
    }
  }, [activeRoleId])

  const hasLive2D = Boolean(role?.live2d_model_id)

  return (
    <div className={[styles.container, className].filter(Boolean).join(' ')}>
      {!activeRoleId && (
        <div className={styles.placeholder}>
          <span className={styles.placeholderIcon} />
          <span className={styles.placeholderText}>未选择角色</span>
        </div>
      )}

      {activeRoleId && !role && (
        <div className={styles.placeholder}>
          <span className={styles.placeholderText}>加载角色中...</span>
        </div>
      )}

      {role && hasLive2D && (
        <div className={styles.live2dContainer}>
          <Live2DViewer
            modelId={role.live2d_model_id!}
            width={width}
            height={height}
          />
          <span className={styles.roleName}>{role.name}</span>
        </div>
      )}

      {role && !hasLive2D && (
        <div className={styles.avatarPlaceholder}>
          {role.avatar_url ? (
            <img
              src={role.avatar_url}
              alt={role.name}
              className={styles.avatar}
              style={{ width, height: height * 0.6 }}
            />
          ) : (
            <div className={styles.avatarFallback} style={{ width, height: height * 0.6 }}>
              {role.name.charAt(0)}
            </div>
          )}
          <span className={styles.roleName}>{role.name}</span>
        </div>
      )}
    </div>
  )
}