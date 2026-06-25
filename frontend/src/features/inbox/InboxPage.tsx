/**
 * 收件箱页面 — 集中管理审批通知、任务结果和系统消息。
 */
import React, { useEffect, useState, useCallback } from 'react';
import { shallow } from 'zustand/shallow';
import { useInboxStore, type InboxMessage } from './store/inboxStore';
import { useI18nStore } from '@/i18n';
import { inboxApi } from './inboxApi';
import { appLogger } from '@/shared/utils/logger';
import { EmptyState } from '@/shared/components/ui';
import styles from './InboxPage.module.css';

const CATEGORY_I18N_KEY: Record<string, string> = {
  notification: 'inbox.filter.notification',
  approval: 'inbox.filter.approval',
  task_result: 'inbox.filter.taskResult',
};

const CATEGORY_ICONS: Record<string, string> = {
  notification: '[MAIL]',
  approval: '[AUTH]',
  task_result: '[DONE]',
};

const InboxPage: React.FC = () => {
  // 使用选择器 + shallow 浅比较，避免整个 store 变化触发重渲染
  const { messages, unreadCount, setMessages, markAsRead, markAllRead, removeMessage } = useInboxStore(s => ({
    messages: s.messages,
    unreadCount: s.unreadCount,
    setMessages: s.setMessages,
    markAsRead: s.markAsRead,
    markAllRead: s.markAllRead,
    removeMessage: s.removeMessage,
  }), shallow);
  const t = useI18nStore(s => s.t);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>('all');
  const [error, setError] = useState('');

  const loadMessages = useCallback(async () => {
    try {
      const data = await inboxApi.list();
      setMessages(data.messages || []);
    } catch (e) {
      setError(t('inbox.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    loadMessages();
    // 每 30 秒轮询新消息
    const interval = setInterval(loadMessages, 30000);
    return () => clearInterval(interval);
  }, [loadMessages]);

  const handleMarkRead = async (msg: InboxMessage) => {
    try {
      await inboxApi.markAsRead(msg.id);
      markAsRead(msg.id);
    } catch (error) {
      appLogger.error({ event: 'inbox_mark_read_failed', module: 'inbox', message: '标记已读失败', extra: { messageId: msg.id, error: error instanceof Error ? error.message : String(error) } });
    }
  };

  const handleMarkAllRead = async () => {
    try {
      await inboxApi.markAllRead(filter !== 'all' ? filter : undefined);
      markAllRead();
    } catch (error) {
      appLogger.error({ event: 'inbox_mark_all_read_failed', module: 'inbox', message: '全部标记已读失败', extra: { error: error instanceof Error ? error.message : String(error) } });
    }
  };

  const handleDelete = async (msg: InboxMessage) => {
    try {
      await inboxApi.delete(msg.id);
      removeMessage(msg.id);
    } catch (error) {
      appLogger.error({ event: 'inbox_delete_failed', module: 'inbox', message: '删除消息失败', extra: { messageId: msg.id, error: error instanceof Error ? error.message : String(error) } });
    }
  };

  const filtered = filter === 'all'
    ? messages
    : messages.filter((m) => m.category === filter);

  if (loading) return <div className={styles.container}><p>{t('app.loading')}</p></div>;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1>{t('inbox.title')}</h1>
          {unreadCount > 0 && (
            <span className={styles.badge}>{t('inbox.unread', { count: String(unreadCount) })}</span>
          )}
        </div>
        <div className={styles.actions}>
          <button className={styles.actionBtn} onClick={handleMarkAllRead}>
            {t('inbox.markAllRead')}
          </button>
        </div>
      </div>

      {error && <div className={styles.error}>{error}</div>}

      <div className={styles.filters}>
        {['all', 'approval', 'task_result', 'notification'].map((cat) => (
          <button
            key={cat}
            className={`${styles.filterBtn} ${filter === cat ? styles.filterActive : ''}`}
            onClick={() => setFilter(cat)}
          >
            {cat === 'all' ? t('inbox.filter.all') : t(CATEGORY_I18N_KEY[cat] || cat)}
          </button>
        ))}
      </div>

      <div className={styles.list}>
        {filtered.length === 0 ? (
          <EmptyState title={t('inbox.empty')} />
        ) : (
          filtered.map((msg) => (
            <div
              key={msg.id}
              className={`${styles.message} ${!msg.read ? styles.unread : ''}`}
              onClick={() => !msg.read && handleMarkRead(msg)}
            >
              <span className={styles.icon}>{CATEGORY_ICONS[msg.category] || '[NOTE]'}</span>
              <div className={styles.msgContent}>
                <div className={styles.msgHeader}>
                  <span className={styles.msgCategory}>
                    {t(CATEGORY_I18N_KEY[msg.category] || msg.category)}
                  </span>
                  <span className={styles.msgTime}>
                    {new Date(msg.created_at).toLocaleString()}
                  </span>
                </div>
                <h3 className={styles.msgTitle}>{msg.title}</h3>
                <p className={styles.msgText}>{msg.content}</p>
                {msg.action_url && msg.action_label && (
                  <a href={msg.action_url} className={styles.msgAction}>
                    {msg.action_label}
                  </a>
                )}
              </div>
              <button
                className={styles.deleteBtn}
                onClick={(e) => { e.stopPropagation(); handleDelete(msg); }}
                title={t('inbox.delete')}
              >
                ×
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default InboxPage;
