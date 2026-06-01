/**
 * 收件箱 API 调用模块。
 */
import api from '@/shared/api/api';

export const inboxApi = {
  list: async (category?: string, unreadOnly = false) => {
    const { data } = await api.get('/inbox', {
      params: { category, unread_only: unreadOnly },
    });
    return data;
  },
  markAsRead: async (messageId: string) => {
    const { data } = await api.post(`/inbox/${messageId}/read`);
    return data;
  },
  markAllRead: async (category?: string) => {
    const { data } = await api.post('/inbox/read-all', null, {
      params: category ? { category } : undefined,
    });
    return data;
  },
  delete: async (messageId: string) => {
    const { data } = await api.delete(`/inbox/${messageId}`);
    return data;
  },
  unreadCount: async () => {
    const { data } = await api.get('/inbox/count');
    return data;
  },
};
