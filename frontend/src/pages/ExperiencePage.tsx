import { useState, useEffect, useCallback } from 'react'
import { experiencesAPI, Experience, ExperienceStats, ExtractionLog } from '../services/experiencesApi'
import ExperienceCard from '../components/ExperienceCard'
import ExperienceModal from '../components/ExperienceModal'
import ExperienceStatsCard from '../components/ExperienceStatsCard'
import ExtractionLogTable from '../components/ExtractionLogTable'
import './ExperiencePage.css'

type TabType = 'list' | 'logs' | 'stats' | 'extract'

interface ExperiencePageProps {
  hideHeader?: boolean
}

function ExperiencePage({ hideHeader = false }: ExperiencePageProps) {
  const [activeTab, setActiveTab] = useState<TabType>('list')
  const [experiences, setExperiences] = useState<Experience[]>([])
  const [selectedExperience, setSelectedExperience] = useState<Experience | null>(null)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [pagination, setPagination] = useState({
    page: 1,
    limit: 20,
    total: 0
  })
  const [filters, setFilters] = useState({
    experience_type: '',
    min_confidence: 0,
    source_task: '',
    sort_by: 'confidence',
    order: 'desc' as 'asc' | 'desc'
  })
  const [stats, setStats] = useState<ExperienceStats | null>(null)
  const [logs, setLogs] = useState<ExtractionLog[]>([])

  const loadExperiences = useCallback(async () => {
    setLoading(true)
    try {
      const response = await experiencesAPI.getExperiences({
        ...filters,
        page: pagination.page,
        limit: pagination.limit
      })
      setExperiences(response.data)
    } catch (error) {
      console.error('Failed to load experiences:', error)
    } finally {
      setLoading(false)
    }
  }, [filters, pagination.page, pagination.limit])

  const loadStats = useCallback(async () => {
    try {
      const response = await experiencesAPI.getStats()
      setStats(response.data)
    } catch (error) {
      console.error('Failed to load stats:', error)
    }
  }, [])

  const loadLogs = useCallback(async () => {
    try {
      const response = await experiencesAPI.getExtractionLogs()
      setLogs(response.data)
    } catch (error) {
      console.error('Failed to load logs:', error)
    }
  }, [])

  useEffect(() => {
    if (activeTab === 'list') {
      loadExperiences()
    }
  }, [activeTab, loadExperiences])

  useEffect(() => {
    if (activeTab === 'stats') {
      loadStats()
    }
  }, [activeTab, loadStats])

  useEffect(() => {
    if (activeTab === 'logs') {
      loadLogs()
    }
  }, [activeTab, loadLogs])

  const handleCreateExperience = () => {
    setSelectedExperience(null)
    setIsModalOpen(true)
  }

  const handleEditExperience = (experience: Experience) => {
    setSelectedExperience(experience)
    setIsModalOpen(true)
  }

  const handleDeleteExperience = async (id: number) => {
    if (!confirm('确定要删除这条经验吗？')) return
    try {
      await experiencesAPI.deleteExperience(id)
      loadExperiences()
    } catch (error) {
      console.error('Failed to delete experience:', error)
    }
  }

  const handleSaveExperience = async (data: Partial<Experience>) => {
    try {
      if (selectedExperience) {
        await experiencesAPI.updateExperience(selectedExperience.id, data)
      } else {
        await experiencesAPI.createExperience(data)
      }
      setIsModalOpen(false)
      loadExperiences()
    } catch (error) {
      console.error('Failed to save experience:', error)
    }
  }

  const getExperienceTypeColor = (type: string): string => {
    const colors: Record<string, string> = {
      strategy: 'blue',
      method: 'green',
      error_pattern: 'red',
      tool_usage: 'purple',
      context_handling: 'orange'
    }
    return colors[type] || 'gray'
  }

  const getExperienceTypeLabel = (type: string): string => {
    const labels: Record<string, string> = {
      strategy: '策略',
      method: '方法',
      error_pattern: '错误模式',
      tool_usage: '工具使用',
      context_handling: '上下文处理'
    }
    return labels[type] || type
  }

  return (
    <div className="experience-page">
      {!hideHeader && (
        <div className="page-header">
          <h1>经验记忆</h1>
          <button className="btn-primary" onClick={handleCreateExperience}>
            + 创建经验
          </button>
        </div>
      )}
      
      {hideHeader && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '16px' }}>
          <button className="btn btn-primary" onClick={handleCreateExperience}>
            + 创建经验
          </button>
        </div>
      )}

      <div className="tabs">
        <button
          className={`tab ${activeTab === 'list' ? 'active' : ''}`}
          onClick={() => setActiveTab('list')}
        >
          经验列表
        </button>
        <button
          className={`tab ${activeTab === 'logs' ? 'active' : ''}`}
          onClick={() => setActiveTab('logs')}
        >
          提取日志
        </button>
        <button
          className={`tab ${activeTab === 'stats' ? 'active' : ''}`}
          onClick={() => setActiveTab('stats')}
        >
          统计概览
        </button>
        <button
          className={`tab ${activeTab === 'extract' ? 'active' : ''}`}
          onClick={() => setActiveTab('extract')}
        >
          手动提取
        </button>
      </div>

      {activeTab === 'list' && (
        <>
          <div className="filters">
            <select
              value={filters.experience_type}
              onChange={(e) => setFilters({ ...filters, experience_type: e.target.value })}
            >
              <option value="">所有类型</option>
              <option value="strategy">策略</option>
              <option value="method">方法</option>
              <option value="error_pattern">错误模式</option>
              <option value="tool_usage">工具使用</option>
              <option value="context_handling">上下文处理</option>
            </select>

            <input
              type="number"
              placeholder="最低置信度"
              value={filters.min_confidence}
              onChange={(e) => setFilters({ ...filters, min_confidence: Number(e.target.value) })}
              min="0"
              max="1"
              step="0.1"
            />

            <input
              type="text"
              placeholder="来源任务"
              value={filters.source_task}
              onChange={(e) => setFilters({ ...filters, source_task: e.target.value })}
            />

            <select
              value={filters.sort_by}
              onChange={(e) => setFilters({ ...filters, sort_by: e.target.value })}
            >
              <option value="confidence">按置信度</option>
              <option value="usage_count">按使用次数</option>
              <option value="created_at">按创建时间</option>
            </select>

            <select
              value={filters.order}
              onChange={(e) => setFilters({ ...filters, order: e.target.value as 'asc' | 'desc' })}
            >
              <option value="desc">降序</option>
              <option value="asc">升序</option>
            </select>
          </div>

          <div className="experience-grid">
            {loading ? (
              <div className="loading">加载中...</div>
            ) : experiences.length === 0 ? (
              <div className="empty-state">暂无经验</div>
            ) : (
              experiences.map((exp) => (
                <ExperienceCard
                  key={exp.id}
                  experience={exp}
                  typeColor={getExperienceTypeColor(exp.experience_type)}
                  typeLabel={getExperienceTypeLabel(exp.experience_type)}
                  onEdit={() => handleEditExperience(exp)}
                  onDelete={() => handleDeleteExperience(exp.id)}
                />
              ))
            )}
          </div>

          <div className="pagination">
            <button
              disabled={pagination.page === 1}
              onClick={() => setPagination({ ...pagination, page: pagination.page - 1 })}
            >
              上一页
            </button>
            <span>第 {pagination.page} 页</span>
            <button onClick={() => setPagination({ ...pagination, page: pagination.page + 1 })}>
              下一页
            </button>
          </div>
        </>
      )}

      {activeTab === 'logs' && (
        <ExtractionLogTable
          logs={logs}
          onReview={async (id, approved) => {
            await experiencesAPI.reviewExperience(id, approved)
            loadLogs()
          }}
        />
      )}

      {activeTab === 'stats' && stats && (
        <div className="stats-container">
          <div className="stats-grid">
            <ExperienceStatsCard
              title="经验总数"
              value={stats.total_experiences}
              icon={<span className="stats-icon-text">E</span>}
            />
            <ExperienceStatsCard
              title="平均置信度"
              value={`${(stats.avg_confidence * 100).toFixed(1)}%`}
              icon={<span className="stats-icon-text">C</span>}
            />
            <ExperienceStatsCard
              title="平均成功率"
              value={`${(stats.avg_success_rate * 100).toFixed(1)}%`}
              icon={<span className="stats-icon-text">S</span>}
            />
            <ExperienceStatsCard
              title="总使用次数"
              value={stats.total_usage}
              icon={<span className="stats-icon-text">U</span>}
            />
          </div>

          <div className="stats-section">
            <h3>类型分布</h3>
            <div className="type-distribution">
              {Object.entries(stats.type_distribution).map(([type, count]) => (
                <div key={type} className="type-item">
                  <span className="type-label">{getExperienceTypeLabel(type)}</span>
                  <span className="type-count">{count}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="stats-section">
            <h3>热门经验</h3>
            <div className="top-experiences">
              {stats.top_experiences.map((exp, index) => (
                <div key={exp.id} className="top-experience-item">
                  <span className="rank">#{index + 1}</span>
                  <span className="title">{exp.title}</span>
                  <span className="usage">{exp.usage_count}次</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {activeTab === 'extract' && (
        <ManualExtractionForm onExtract={loadLogs} />
      )}

      {isModalOpen && (
        <ExperienceModal
          experience={selectedExperience}
          onSave={handleSaveExperience}
          onClose={() => setIsModalOpen(false)}
        />
      )}
    </div>
  )
}

function ManualExtractionForm({ onExtract }: { onExtract: () => void }) {
  const [formData, setFormData] = useState({
    session_id: '',
    user_goal: '',
    execution_steps: '',
    final_result: '',
    status: 'success'
  })
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const steps = formData.execution_steps.split('\n').map((step, i) => ({
        action: `步骤${i + 1}`,
        result: step
      }))

      const response = await experiencesAPI.extractExperience({
        ...formData,
        execution_steps: steps
      })

      setResult(`成功提取经验：${response.data.experience.title}`)
      onExtract()
    } catch (error) {
      setResult('提取失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form className="extraction-form" onSubmit={handleSubmit}>
      <h3>手动提取经验</h3>

      <div className="form-group">
        <label>会话ID</label>
        <input
          type="text"
          value={formData.session_id}
          onChange={(e) => setFormData({ ...formData, session_id: e.target.value })}
          required
        />
      </div>

      <div className="form-group">
        <label>用户目标</label>
        <textarea
          value={formData.user_goal}
          onChange={(e) => setFormData({ ...formData, user_goal: e.target.value })}
          required
        />
      </div>

      <div className="form-group">
        <label>执行步骤（每行一个）</label>
        <textarea
          value={formData.execution_steps}
          onChange={(e) => setFormData({ ...formData, execution_steps: e.target.value })}
          placeholder="步骤1&#10;步骤2&#10;步骤3"
          required
        />
      </div>

      <div className="form-group">
        <label>最终结果</label>
        <textarea
          value={formData.final_result}
          onChange={(e) => setFormData({ ...formData, final_result: e.target.value })}
          required
        />
      </div>

      <div className="form-group">
        <label>任务状态</label>
        <select
          value={formData.status}
          onChange={(e) => setFormData({ ...formData, status: e.target.value })}
        >
          <option value="success">成功</option>
          <option value="failure">失败</option>
        </select>
      </div>

      <button type="submit" className="btn-primary" disabled={loading}>
        {loading ? '提取中...' : '提取经验'}
      </button>

      {result && <div className="result-message">{result}</div>}
    </form>
  )
}

export default ExperiencePage
