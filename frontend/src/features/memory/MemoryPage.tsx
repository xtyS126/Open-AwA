import { useState, useEffect } from 'react'
import { memoryAPI } from '@/shared/api/api'
import { ShortTermMemory, LongTermMemory } from '@/shared/types/api'
import ExperiencePage from '@/features/experiences/ExperiencePage'
import styles from './MemoryPage.module.css'

function MemoryPage() {
  const [activeTab, setActiveTab] = useState('short-term')
  const [shortTermMemories, setShortTermMemories] = useState<ShortTermMemory[]>([])
  const [longTermMemories, setLongTermMemories] = useState<LongTermMemory[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (activeTab === 'short-term' || activeTab === 'long-term') {
      loadMemories()
    }
  }, [activeTab])

  const loadMemories = async () => {
    setLoading(true)
    try {
      if (activeTab === 'short-term') {
        const response = await memoryAPI.getShortTerm('default')
        setShortTermMemories(response.data)
      } else {
        const response = await memoryAPI.getLongTerm()
        setLongTermMemories(response.data)
      }
    } catch (error) {
      throw error
    } finally {
      setLoading(false)
    }
  }

  const handleDeleteShortTerm = async (id: number) => {
    try {
      await memoryAPI.deleteShortTerm(id)
      loadMemories()
    } catch (error) {
      throw error
    }
  }

  const handleDeleteLongTerm = async (id: number) => {
    try {
      await memoryAPI.deleteLongTerm(id)
      loadMemories()
    } catch (error) {
      throw error
    }
  }

  if (loading) {
    return <div className={styles['loading']}>加载中...</div>
  }

  return (
    <div className={styles['memory-page']}>
      <div className={styles['page-header']}>
        <h1>记忆管理</h1>
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
        <button
          className={`${styles['tab-btn']} ${activeTab === 'experience' ? styles['active'] : ''}`}
          onClick={() => setActiveTab('experience')}
        >
          经验记忆
        </button>
      </div>

      <div className={styles['memory-content']}>
        {activeTab === 'experience' && (
          <div className={styles['experience-tab-content']}>
            <ExperiencePage hideHeader={true} />
          </div>
        )}

        {activeTab === 'short-term' && (
          <div className={styles['memory-list']}>
            {shortTermMemories.length === 0 ? (
              <div className={styles['empty-state']}>
                <p>暂无短期记忆</p>
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
                      className={`${styles['btn']} ${styles['btn-danger']} ${styles['btn-sm']}`}
                      onClick={() => handleDeleteShortTerm(memory.id)}
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
                      className={`${styles['btn']} ${styles['btn-danger']} ${styles['btn-sm']}`}
                      onClick={() => handleDeleteLongTerm(memory.id)}
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
