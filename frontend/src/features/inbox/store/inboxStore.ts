/**
 * 收件箱 Zustand 状态管理。
 */
// [Fix] 消费方使用 shallow equalityFn，改用 createWithEqualityFn 消除 zustand 弃用警告
import { createWithEqualityFn } from 'zustand/traditional';

export interface InboxMessage {
  id: string;
  title: string;
  content: string;
  category: 'notification' | 'approval' | 'task_result';
  read: boolean;
  action_url: string | null;
  action_label: string | null;
  created_at: string;
}

export type InboxStreamStatus = 'disconnected' | 'connecting' | 'connected' | 'unavailable';

interface InboxStore {
  messages: InboxMessage[];
  unreadCount: number;
  streamStatus: InboxStreamStatus;
  setMessages: (messages: InboxMessage[]) => void;
  setStreamStatus: (status: InboxStreamStatus) => void;
  /** 新增单条消息（WebSocket 实时推送时使用），插入列表顶部，已存在则跳过去重 */
  addMessage: (message: InboxMessage) => void;
  markAsRead: (id: string) => void;
  markAllRead: () => void;
  removeMessage: (id: string) => void;
  resetForLogout: () => void;
}

export const useInboxStore = createWithEqualityFn<InboxStore>((set, get) => ({
  messages: [],
  unreadCount: 0,
  streamStatus: 'disconnected',
  setMessages: (messages) => set({
    messages,
    unreadCount: messages.filter((m) => !m.read).length,
  }),
  setStreamStatus: (streamStatus) => set({ streamStatus }),
  addMessage: (message) => {
    const existing = get().messages;
    // 去重：避免 WS 推送与轮询拉取产生重复条目
    if (existing.some((m) => m.id === message.id)) return;
    const messages = [message, ...existing];
    set({
      messages,
      unreadCount: messages.filter((m) => !m.read).length,
    });
  },
  markAsRead: (id) => {
    const messages = get().messages.map((m) =>
      m.id === id ? { ...m, read: true } : m
    );
    set({ messages, unreadCount: messages.filter((m) => !m.read).length });
  },
  markAllRead: () => {
    const messages = get().messages.map((m) => ({ ...m, read: true }));
    set({ messages, unreadCount: 0 });
  },
  removeMessage: (id) => {
    const messages = get().messages.filter((m) => m.id !== id);
    set({ messages, unreadCount: messages.filter((m) => !m.read).length });
  },
  resetForLogout: () => set({ messages: [], unreadCount: 0, streamStatus: 'disconnected' }),
}));
