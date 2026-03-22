import { useState, useEffect } from 'react'
import { memoryAPI } from '../services/api'
import { ShortTermMemory, LongTermMemory } from '../types/api'
import './MemoryPage.css'

function MemoryPage() {
  const [activeTab, setActiveTab] = useState('short-term')
  const [shortTermMemories, setShortTermMemories] = useState<ShortTermMemory[]>([])
  const [longTermMemories, setLongTermMemories] = useState<LongTermMemory[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadMemories()
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
    return <div className="loading">加载中...</div>
  }

  return (
    <div className="memory-page">
      <div className="page-header">
        <h1>记忆管理</h1>
      </div>

      <div className="memory-tabs">
        <button
          className={`tab-btn ${activeTab === 'short-term' ? 'active' : ''}`}
          onClick={() => setActiveTab('short-term')}
        >
          短期记忆
        </button>
        <button
          className={`tab-btn ${activeTab === 'long-term' ? 'active' : ''}`}
          onClick={() => setActiveTab('long-term')}
        >
          长期记忆
        </button>
      </div>

      <div className="memory-content">
        {activeTab === 'short-term' && (
          <div className="memory-list">
            {shortTermMemories.length === 0 ? (
              <div className="empty-state">
                <p>暂无短期记忆</p>
              </div>
            ) : (
              shortTermMemories.map((memory) => (
                <div key={memory.id} className="memory-card">
                  <div className="memory-role">{memory.role}</div>
                  <p className="memory-content-text">{memory.content}</p>
                  <div className="memory-footer">
                    <span className="memory-time">
                      {new Date(memory.timestamp).toLocaleString()}
                    </span>
                    <button
                      className="btn btn-danger btn-sm"
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
          <div className="memory-list">
            {longTermMemories.length === 0 ? (
              <div className="empty-state">
                <p>暂无长期记忆</p>
              </div>
            ) : (
              longTermMemories.map((memory) => (
                <div key={memory.id} className="memory-card">
                  <p className="memory-content-text">{memory.content}</p>
                  <div className="memory-footer">
                    <span className="memory-importance">
                      重要性: {memory.importance.toFixed(1)}
                    </span>
                    <span className="memory-access">
                      访问: {memory.access_count}次
                    </span>
                    <button
                      className="btn btn-danger btn-sm"
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
