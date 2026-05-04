import { useCallback, useEffect, useState } from 'react'
import { conversationAPI, memoryAPI } from '@/shared/api/api'
import { ShortTermMemory, LongTermMemory } from '@/shared/types/api'
import { useChatStore } from '@/features/chat/store/chatStore'
import { appLogger } from '@/shared/utils/logger'
import styles from './MemoryPage.module.css'

function getErrorMessage(error: unknown, fallback: string): string {
  const maybeError = error as { response?: { status?: number, data?: { detail?: string } } }
  const status = maybeError?.response?.status
  const detail = maybeError?.response?.data?.detail

  if (status === 403) {
    return '当前会话不属于你，无法查看对应短期记忆，请先在聊天页发起新的对话。'
  }

  return typeof detail === 'string' && detail.trim() ? detail : fallback
}

function MemoryPage() {
  const [activeTab, setActiveTab] = useState('short-term')
  const [shortTermMemories, setShortTermMemories] = useState<ShortTermMemory[]>([])
  const [longTermMemories, setLongTermMemories] = useState<LongTermMemory[]>([])
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [selectedSessionId, setSelectedSessionId] = useState('')
  const [shortTermEmptyMessage, setShortTermEmptyMessage] = useState('暂无短期记忆')
  const chatSessionId = useChatStore((state) => state.sessionId)

  const getCandidateSessionIds = useCallback(async () => {
    const candidates = new Set<string>()

    if (chatSessionId && chatSessionId !== 'default') {
      candidates.add(chatSessionId)
    }

    const response = await conversationAPI.getRecordsPreview(20)
    for (const record of response.data.records || []) {
      const sessionId = String(record.session_id || '').trim()
      if (sessionId) {
        candidates.add(sessionId)
      }
    }

    return Array.from(candidates)
  }, [chatSessionId])

  const loadShortTermMemories = useCallback(async () => {
    const candidateSessionIds = await getCandidateSessionIds()

    if (candidateSessionIds.length === 0) {
      setSelectedSessionId('')
      setShortTermMemories([])
      setShortTermEmptyMessage('暂无可用会话，请先在聊天页发起一次对话。')
      return
    }

    for (const sessionId of candidateSessionIds) {
      try {
        const response = await memoryAPI.getShortTerm(sessionId)
        setSelectedSessionId(sessionId)
        setShortTermMemories(response.data)
        setShortTermEmptyMessage(response.data.length === 0 ? '当前会话暂无短期记忆' : '暂无短期记忆')
        return
      } catch (error) {
        const status = (error as { response?: { status?: number } })?.response?.status
        if (status === 403) {
          continue
        }
        throw error
      }
    }

    setSelectedSessionId('')
    setShortTermMemories([])
    setShortTermEmptyMessage('未找到当前账号可访问的会话，请先在聊天页发起新的对话。')
  }, [getCandidateSessionIds])

  const loadMemories = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      if (activeTab === 'short-term') {
        await loadShortTermMemories()
      } else {
        const response = await memoryAPI.getLongTerm()
        setSelectedSessionId('')
        setLongTermMemories(response.data)
      }
    } catch (error) {
      appLogger.error({
        event: 'memory_page_load_failed',
        module: 'memory',
        action: 'load',
        status: 'failure',
        message: '加载记忆失败',
        extra: {
          tab: activeTab,
          error: error instanceof Error ? error.message : String(error),
        },
      })
      if (activeTab === 'short-term') {
        setShortTermMemories([])
      } else {
        setLongTermMemories([])
      }
      setLoadError(getErrorMessage(error, activeTab === 'short-term' ? '加载短期记忆失败，请稍后重试' : '加载长期记忆失败，请稍后重试'))
    } finally {
      setLoading(false)
    }
  }, [activeTab, loadShortTermMemories])

  useEffect(() => {
    if (activeTab === 'short-term' || activeTab === 'long-term') {
      void loadMemories()
    }
  }, [activeTab, loadMemories])

  const handleDeleteShortTerm = async (id: number) => {
    setActionError(null)
    try {
      await memoryAPI.deleteShortTerm(id)
      await loadMemories()
    } catch (error) {
      appLogger.error({
        event: 'memory_page_delete_short_term_failed',
        module: 'memory',
        action: 'delete_short_term',
        status: 'failure',
        message: '删除短期记忆失败',
        extra: { memory_id: id, error: error instanceof Error ? error.message : String(error) },
      })
      setActionError(getErrorMessage(error, '删除短期记忆失败，请稍后重试'))
    }
  }

  const handleDeleteLongTerm = async (id: number) => {
    setActionError(null)
    try {
      await memoryAPI.deleteLongTerm(id)
      await loadMemories()
    } catch (error) {
      appLogger.error({
        event: 'memory_page_delete_long_term_failed',
        module: 'memory',
        action: 'delete_long_term',
        status: 'failure',
        message: '删除长期记忆失败',
        extra: { memory_id: id, error: error instanceof Error ? error.message : String(error) },
      })
      setActionError(getErrorMessage(error, '删除长期记忆失败，请稍后重试'))
    }
  }

  if (loading) {
    return <div className={styles['loading']}>加载中...</div>
  }

  return (
    <div className={styles['memory-page']}>
      <div className={styles['page-header']}>
        <h1>记忆管理</h1>
        <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={() => void loadMemories()} disabled={loading}>
          刷新当前列表
        </button>
      </div>

      <div className={styles['memory-tabs']}>
        <button
          className={`${styles['tab-btn']} ${activeTab === 'short-term' ? styles['active'] : ''}`}
          onClick={() => setActiveTab('short-term')}
        >
          短期记忆
        </button>
        <button
          className={`${styles['tab-btn']} ${activeTab === 'long-term' ? styles['active'] : ''}`}
          onClick={() => setActiveTab('long-term')}
        >
          长期记忆
        </button>
      </div>

      <div className={styles['memory-content']}>
        {loadError && (
          <div className={styles['status-message-error']}>{loadError}</div>
        )}
        {actionError && (
          <div className={styles['status-message-error']}>{actionError}</div>
        )}

        {activeTab === 'short-term' && (
          <div className={styles['memory-list']}>
            {selectedSessionId && (
              <div className={styles['session-hint']}>
                当前查看会话：{selectedSessionId}
              </div>
            )}
            {shortTermMemories.length === 0 ? (
              <div className={styles['empty-state']}>
                <p>{shortTermEmptyMessage}</p>
              </div>
            ) : (
              shortTermMemories.map((memory) => (
                <div key={memory.id} className={styles['memory-card']}>
                  <div className={styles['memory-role']}>{memory.role}</div>
                  <p className={styles['memory-content-text']}>{memory.content}</p>
                  <div className={styles['memory-footer']}>
                    <span className={styles['memory-time']}>
                      {new Date(memory.timestamp).toLocaleString()}
                    </span>
                    <button
                      className={`btn ${styles['btn-danger'] || 'btn-danger'} ${styles['btn-sm']}`}
                      onClick={() => void handleDeleteShortTerm(memory.id)}
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'long-term' && (
          <div className={styles['memory-list']}>
            {longTermMemories.length === 0 ? (
              <div className={styles['empty-state']}>
                <p>暂无长期记忆</p>
              </div>
            ) : (
              longTermMemories.map((memory) => (
                <div key={memory.id} className={styles['memory-card']}>
                  <p className={styles['memory-content-text']}>{memory.content}</p>
                  <div className={styles['memory-footer']}>
                    <span className={styles['memory-importance']}>
                      重要性: {memory.importance.toFixed(1)}
                    </span>
                    <span className={styles['memory-access']}>
                      访问: {memory.access_count}次
                    </span>
                    <button
                      className={`btn ${styles['btn-danger'] || 'btn-danger'} ${styles['btn-sm']}`}
                      onClick={() => void handleDeleteLongTerm(memory.id)}
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default MemoryPage
