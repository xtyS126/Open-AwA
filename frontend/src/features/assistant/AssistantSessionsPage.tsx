import { useState } from 'react'
import { Plus } from 'lucide-react'
import { useNavigate } from '@/shared/routing'
import { useI18nStore } from '@/i18n'
import PageLayout from '@/shared/components/PageLayout/PageLayout'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import ConversationManager from '@/features/chat/components/ConversationManager'
import { useConversationHistory } from '@/features/chat/hooks/useConversationHistory'
import { useConversationListActions } from '@/features/chat/hooks/useConversationListActions'
import { useChatBroadcast } from '@/features/chat/hooks/useChatBroadcast'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import styles from './AssistantSessionsPage.module.css'

/** 独立会话管理页，不加载聊天消息，也不在访问时自动创建会话。 */
export default function AssistantSessionsPage() {
  const navigate = useNavigate()
  const t = useI18nStore((state) => state.t)
  const conversations = useSessionStore((state) => state.conversations)
  const activeSessionId = useSessionStore((state) => state.sessionId)
  const hasMore = useSessionStore((state) => state.conversationsHasMore)
  const upsertConversation = useSessionStore((state) => state.upsertConversation)
  const removeConversation = useSessionStore((state) => state.removeConversation)
  const [actionError, setActionError] = useState<string | null>(null)
  const {
    historyLoading,
    historyError,
    historySearchInput,
    historySort,
    historyPage,
    includeDeleted,
    setHistorySearchInput,
    setHistorySort,
    setIncludeDeleted,
    loadConversationList,
  } = useConversationHistory()
  const { broadcastConversationChange } = useChatBroadcast()
  const actions = useConversationListActions({
    conversations,
    activeSessionId,
    includeDeleted,
    loading: historyLoading,
    page: historyPage,
    hasMore,
    loadConversationList,
    upsertConversation,
    removeConversation,
    broadcastConversationChange,
    onConversationCreated: (sessionId) => navigate(`/assistant/sessions/${sessionId}`),
  })

  const createConversation = async () => {
    setActionError(null)
    try {
      await actions.createConversation()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : '新建会话失败')
    }
  }

  return (
    <PageLayout
      title="会话管理"
      className={styles.page}
      actions={(
        <button
          type="button"
          className={styles.createButton}
          onClick={() => void createConversation()}
        >
          <Plus size={18} aria-hidden="true" />
          {t('chat.history.newChat')}
        </button>
      )}
    >
      <section className={styles.card} aria-label="会话列表">
        <p className={styles.description}>
          搜索、整理或恢复历史会话。打开会话后才会加载对应聊天内容。
        </p>
        {actionError && (
          <div className={styles.alert} role="alert">
            {actionError}
          </div>
        )}
        <ConversationManager
          loading={historyLoading}
          error={actionError ? null : historyError}
          conversations={conversations}
          activeSessionId={activeSessionId}
          search={historySearchInput}
          sortBy={historySort}
          includeDeleted={includeDeleted}
          hasMore={hasMore}
          onSearchChange={setHistorySearchInput}
          onSortChange={setHistorySort}
          onIncludeDeletedChange={setIncludeDeleted}
          onSelectConversation={(sessionId) => {
            void navigate(`/assistant/sessions/${sessionId}`)
          }}
          onRenameConversation={actions.handleRenameConversation}
          onDeleteConversation={actions.handleDeleteConversation}
          onBatchDeleteConversations={actions.handleBatchDeleteConversations}
          onRestoreConversation={actions.handleRestoreConversation}
          onLoadMore={actions.handleLoadMoreConversations}
        />
      </section>

      {actions.pendingDeleteSessionId && (
        <ConfirmDialog
          isOpen
          title="删除会话"
          message={t('chat.confirmDeleteConversation')}
          type="danger"
          confirmText="删除"
          cancelText={t('app.cancel')}
          onConfirm={() => void actions.confirmDeleteConversation()}
          onCancel={actions.cancelDeleteConversation}
        />
      )}
      {actions.pendingBatchDeleteIds && actions.pendingBatchDeleteIds.length > 0 && (
        <ConfirmDialog
          isOpen
          title="批量删除会话"
          message={t('chat.confirmDeleteSelected', {
            count: String(actions.pendingBatchDeleteIds.length),
          })}
          type="danger"
          confirmText="删除"
          cancelText={t('app.cancel')}
          onConfirm={() => void actions.confirmBatchDeleteConversations()}
          onCancel={actions.cancelBatchDeleteConversations}
        />
      )}
    </PageLayout>
  )
}
