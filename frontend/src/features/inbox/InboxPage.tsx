/**
 * 收件箱页面 — 集中管理审批通知、任务结果和系统消息。
 */
import React, { useEffect, useState, useCallback } from 'react';
import { useInboxStore, type InboxMessage } from './store/inboxStore';
import { inboxApi } from './inboxApi';
import styles from './InboxPage.module.css';

const CATEGORY_LABELS: Record<string, string> = {
  notification: '通知',
  approval: '审批',
  task_result: '任务结果',
};

const CATEGORY_ICONS: Record<string, string> = {
  notification: '📬',
  approval: '🔐',
  task_result: '✅',
};

const InboxPage: React.FC = () => {
  const { messages, unreadCount, setMessages, markAsRead, markAllRead, removeMessage } = useInboxStore();
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>('all');
  const [error, setError] = useState('');

  useEffect(() => {
    loadMessages();
    // 每 30 秒轮询新消息
    const interval = setInterval(loadMessages, 30000);
    return () => clearInterval(interval);
  }, []);

  const loadMessages = useCallback(async () => {
    try {
      const data = await inboxApi.list();
      setMessages(data.messages || []);
    } catch (e) {
      setError('加载收件箱失败');
    } finally {
      setLoading(false);
    }
  }, []);

  const handleMarkRead = async (msg: InboxMessage) => {
    try {
      await inboxApi.markAsRead(msg.id);
      markAsRead(msg.id);
    } catch {}
  };

  const handleMarkAllRead = async () => {
    try {
      await inboxApi.markAllRead(filter !== 'all' ? filter : undefined);
      markAllRead();
    } catch {}
  };

  const handleDelete = async (msg: InboxMessage) => {
    try {
      await inboxApi.delete(msg.id);
      removeMessage(msg.id);
    } catch {}
  };

  const filtered = filter === 'all'
    ? messages
    : messages.filter((m) => m.category === filter);

  if (loading) return <div className={styles.container}><p>加载中...</p></div>;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div>
          <h1>收件箱</h1>
          {unreadCount > 0 && (
            <span className={styles.badge}>{unreadCount} 条未读</span>
          )}
        </div>
        <div className={styles.actions}>
          <button className={styles.actionBtn} onClick={handleMarkAllRead}>
            全部已读
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
            {cat === 'all' ? '全部' : CATEGORY_LABELS[cat] || cat}
          </button>
        ))}
      </div>

      <div className={styles.list}>
        {filtered.length === 0 ? (
          <p className={styles.empty}>暂无消息</p>
        ) : (
          filtered.map((msg) => (
            <div
              key={msg.id}
              className={`${styles.message} ${!msg.read ? styles.unread : ''}`}
              onClick={() => !msg.read && handleMarkRead(msg)}
            >
              <span className={styles.icon}>{CATEGORY_ICONS[msg.category] || '📌'}</span>
              <div className={styles.msgContent}>
                <div className={styles.msgHeader}>
                  <span className={styles.msgCategory}>
                    {CATEGORY_LABELS[msg.category] || msg.category}
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
                title="删除"
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
