/**
 * 通知 API 模块。
 * 封装通知的列表查询与创建接口，供 vibe-coding 等模块订阅和展示通知。
 *
 * 注意：SSE 流式推送端点（GET /notifications/stream）不在此封装，
 * 由组件直接用 EventSource 订阅，以保持长连接的生命周期可控。
 */
import api from '@/shared/api/api'

const BASE = '/notifications'

/** 通知项 */
export interface NotificationItem {
  /** 通知 ID */
  id: string
  /** 标题 */
  title: string
  /** 正文内容（可选） */
  body?: string
  /** 关联面板 ID（可选，用于路由跳转） */
  pane_id?: string
  /** 通知类型（可选，用于颜色/图标标识） */
  notification_type?: string
  /** 创建时间（ISO 字符串） */
  created_at: string
}

/** 创建通知请求体 */
export interface CreateNotificationPayload {
  title: string
  body?: string
  pane_id?: string
  notification_type?: string
}

/** 列出通知响应 */
export interface NotificationsListResponse {
  notifications: NotificationItem[]
  count: number
}

/** 列出通知 */
export async function listNotifications(limit?: number): Promise<NotificationsListResponse> {
  const { data } = await api.get<NotificationsListResponse>(BASE, {
    params: limit !== undefined ? { limit } : undefined,
  })
  return data
}

/** 创建通知 */
export async function sendNotification(payload: CreateNotificationPayload): Promise<NotificationItem> {
  const { data } = await api.post<NotificationItem>(BASE, payload)
  return data
}
