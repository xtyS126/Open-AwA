import { useCallback, useState } from 'react'
import { conversationAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import type { ConversationSessionSummary } from '@/features/chat/types'

export interface UseConversationListActionsParams {
  conversations: ConversationSessionSummary[]
  activeSessionId?: string
  includeDeleted: boolean
  loading: boolean
  page: number
  hasMore: boolean
  loadConversationList: (page: number, append: boolean, force?: boolean) => Promise<void>
  upsertConversation: (conversation: ConversationSessionSummary) => void
  removeConversation: (sessionId: string) => void
  broadcastConversationChange: () => void
  onConversationCreated?: (sessionId: string) => Promise<void> | void
  onActiveConversationDeleted?: (nextConversation: ConversationSessionSummary | null) => Promise<void> | void
  onConversationRestored?: (sessionId: string) => Promise<void> | void
}

export interface UseConversationListActionsReturn {
  createConversation: () => Promise<ConversationSessionSummary>
  handleRenameConversation: (sessionId: string, title: string) => Promise<void>
  handleDeleteConversation: (sessionId: string) => void
  cancelDeleteConversation: () => void
  confirmDeleteConversation: () => Promise<void>
  handleRestoreConversation: (sessionId: string) => Promise<void>
  handleLoadMoreConversations: () => void
  handleBatchDeleteConversations: (sessionIds: string[]) => void
  cancelBatchDeleteConversations: () => void
  confirmBatchDeleteConversations: () => Promise<void>
  pendingDeleteSessionId: string | null
  pendingBatchDeleteIds: string[] | null
}

/**
 * 管理会话列表自身的增删改恢复动作。
 *
 * 本 Hook 不在 mount 时加载列表，也不读取消息 Store。路由跳转和聊天消息清理由消费方回调处理。
 */
export function useConversationListActions({
  conversations,
  activeSessionId,
  includeDeleted,
  loading,
  page,
  hasMore,
  loadConversationList,
  upsertConversation,
  removeConversation,
  broadcastConversationChange,
  onConversationCreated,
  onActiveConversationDeleted,
  onConversationRestored,
}: UseConversationListActionsParams): UseConversationListActionsReturn {
  const [pendingDeleteSessionId, setPendingDeleteSessionId] = useState<string | null>(null)
  const [pendingBatchDeleteIds, setPendingBatchDeleteIds] = useState<string[] | null>(null)

  const refreshConversationList = useCallback(async () => {
    await loadConversationList(1, false, true)
  }, [loadConversationList])

  const createConversation = useCallback(async () => {
    const response = await conversationAPI.createSession()
    const conversation = response.data as ConversationSessionSummary
    upsertConversation(conversation)
    await refreshConversationList()
    broadcastConversationChange()
    await onConversationCreated?.(conversation.session_id)
    return conversation
  }, [broadcastConversationChange, onConversationCreated, refreshConversationList, upsertConversation])

  const handleRenameConversation = useCallback(async (sessionId: string, title: string) => {
    const response = await conversationAPI.renameSession(sessionId, title)
    upsertConversation(response.data as ConversationSessionSummary)
    broadcastConversationChange()
  }, [broadcastConversationChange, upsertConversation])

  const handleDeleteConversation = useCallback((sessionId: string) => {
    setPendingDeleteSessionId(sessionId)
  }, [])

  const cancelDeleteConversation = useCallback(() => {
    setPendingDeleteSessionId(null)
  }, [])

  const confirmDeleteConversation = useCallback(async () => {
    if (!pendingDeleteSessionId) {
      return
    }

    const targetSessionId = pendingDeleteSessionId
    const nextConversation = conversations.find(
      (conversation) => conversation.session_id !== targetSessionId && !conversation.deleted_at,
    ) ?? null
    setPendingDeleteSessionId(null)

    try {
      const response = await conversationAPI.deleteSession(targetSessionId)
      if (includeDeleted) {
        upsertConversation(response.data as ConversationSessionSummary)
      } else {
        removeConversation(targetSessionId)
      }
      if (activeSessionId === targetSessionId) {
        await onActiveConversationDeleted?.(nextConversation)
      }
      await refreshConversationList()
      broadcastConversationChange()
    } catch (error) {
      setPendingDeleteSessionId(targetSessionId)
      appLogger.warning({
        event: 'conversation_delete_failed',
        module: 'chat',
        action: 'delete',
        status: 'failure',
        message: 'delete conversation failed',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    }
  }, [activeSessionId, broadcastConversationChange, conversations, includeDeleted, onActiveConversationDeleted, pendingDeleteSessionId, refreshConversationList, removeConversation, upsertConversation])

  const handleRestoreConversation = useCallback(async (sessionId: string) => {
    const response = await conversationAPI.restoreSession(sessionId)
    upsertConversation(response.data as ConversationSessionSummary)
    await onConversationRestored?.(sessionId)
    await refreshConversationList()
    broadcastConversationChange()
  }, [broadcastConversationChange, onConversationRestored, refreshConversationList, upsertConversation])

  const handleLoadMoreConversations = useCallback(() => {
    if (loading || !hasMore) {
      return
    }
    void loadConversationList(page + 1, true)
  }, [hasMore, loadConversationList, loading, page])

  const handleBatchDeleteConversations = useCallback((sessionIds: string[]) => {
    if (sessionIds.length > 0) {
      setPendingBatchDeleteIds(sessionIds)
    }
  }, [])

  const cancelBatchDeleteConversations = useCallback(() => {
    setPendingBatchDeleteIds(null)
  }, [])

  const confirmBatchDeleteConversations = useCallback(async () => {
    if (!pendingBatchDeleteIds || pendingBatchDeleteIds.length === 0) {
      return
    }

    const targetSessionIds = pendingBatchDeleteIds
    const activeConversationDeleted = Boolean(activeSessionId && targetSessionIds.includes(activeSessionId))
    const nextConversation = conversations.find(
      (conversation) => !targetSessionIds.includes(conversation.session_id) && !conversation.deleted_at,
    ) ?? null
    setPendingBatchDeleteIds(null)

    try {
      const response = await conversationAPI.batchDeleteSessions(targetSessionIds)
      if (includeDeleted) {
        for (const conversation of response.data.items ?? []) {
          upsertConversation(conversation as ConversationSessionSummary)
        }
      } else {
        for (const sessionId of targetSessionIds) {
          removeConversation(sessionId)
        }
      }
      if (activeConversationDeleted) {
        await onActiveConversationDeleted?.(nextConversation)
      }
      await refreshConversationList()
      broadcastConversationChange()
    } catch (error) {
      setPendingBatchDeleteIds(targetSessionIds)
      appLogger.warning({
        event: 'conversation_batch_delete_failed',
        module: 'chat',
        action: 'batch_delete',
        status: 'failure',
        message: 'batch delete conversations failed',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    }
  }, [activeSessionId, broadcastConversationChange, conversations, includeDeleted, onActiveConversationDeleted, pendingBatchDeleteIds, refreshConversationList, removeConversation, upsertConversation])

  return {
    createConversation,
    handleRenameConversation,
    handleDeleteConversation,
    cancelDeleteConversation,
    confirmDeleteConversation,
    handleRestoreConversation,
    handleLoadMoreConversations,
    handleBatchDeleteConversations,
    cancelBatchDeleteConversations,
    confirmBatchDeleteConversations,
    pendingDeleteSessionId,
    pendingBatchDeleteIds,
  }
}
