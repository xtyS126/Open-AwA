/**
 * 收件箱 Zustand 状态管理。
 */
import { create } from 'zustand';

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

interface InboxStore {
  messages: InboxMessage[];
  unreadCount: number;
  setMessages: (messages: InboxMessage[]) => void;
  markAsRead: (id: string) => void;
  markAllRead: () => void;
  removeMessage: (id: string) => void;
}

export const useInboxStore = create<InboxStore>((set, get) => ({
  messages: [],
  unreadCount: 0,
  setMessages: (messages) => set({
    messages,
    unreadCount: messages.filter((m) => !m.read).length,
  }),
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
}));
