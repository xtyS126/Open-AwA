/**
 * 收件箱 API 调用模块。
 * 类型与 backend/api/routes/inbox.py 中的响应结构保持一致。
 */
import api from '@/shared/api/api';
import type { InboxMessage } from './store/inboxStore';

/** 列表响应：与 backend list_messages 返回结构一致。 */
export interface InboxListResponse {
  messages: InboxMessage[];
  total: number;
  unread: number;
}

/** 单条操作结果。 */
export interface InboxMutationResult {
  message: string;
  id?: string;
}

/** 全部标记已读响应。 */
export interface InboxMarkAllReadResult {
  message: string;
  count: number;
}

/** 未读数量响应。 */
export interface InboxUnreadCountResult {
  unread: number;
}

export const inboxApi = {
  /** 获取收件箱消息列表，可按类别筛选或仅未读。 */
  list: async (category?: string, unreadOnly = false): Promise<InboxListResponse> => {
    const { data } = await api.get<InboxListResponse>('/inbox', {
      params: { category, unread_only: unreadOnly },
    });
    return data;
  },
  /** 标记单条消息为已读。 */
  markAsRead: async (messageId: string): Promise<InboxMutationResult> => {
    const { data } = await api.post<InboxMutationResult>(`/inbox/${messageId}/read`);
    return data;
  },
  /** 标记全部（或指定类别）消息为已读。 */
  markAllRead: async (category?: string): Promise<InboxMarkAllReadResult> => {
    const { data } = await api.post<InboxMarkAllReadResult>('/inbox/read-all', null, {
      params: category ? { category } : undefined,
    });
    return data;
  },
  /** 删除单条消息。 */
  delete: async (messageId: string): Promise<InboxMutationResult> => {
    const { data } = await api.delete<InboxMutationResult>(`/inbox/${messageId}`);
    return data;
  },
  /** 获取未读消息数量。 */
  unreadCount: async (): Promise<InboxUnreadCountResult> => {
    const { data } = await api.get<InboxUnreadCountResult>('/inbox/count');
    return data;
  },
};
