import { useState, useEffect } from 'react'
import { Experience } from '../services/experiencesApi'

interface Props {
  experience: Experience | null
  onSave: (data: Partial<Experience>) => void
  onClose: () => void
}

function ExperienceModal({ experience, onSave, onClose }: Props) {
  const [formData, setFormData] = useState({
    experience_type: 'method' as 'strategy' | 'method' | 'error_pattern' | 'tool_usage' | 'context_handling',
    title: '',
    content: '',
    trigger_conditions: '',
    confidence: 0.5,
    source_task: 'general'
  })

  useEffect(() => {
    if (experience) {
      setFormData({
        experience_type: experience.experience_type,
        title: experience.title,
        content: experience.content,
        trigger_conditions: experience.trigger_conditions,
        confidence: experience.confidence,
        source_task: experience.source_task
      })
    }
  }, [experience])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSave(formData)
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <h2>{experience ? '编辑经验' : '创建经验'}</h2>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>经验类型</label>
            <select
              value={formData.experience_type}
              onChange={(e) => setFormData({ ...formData, experience_type: e.target.value as any })}
            >
              <option value="strategy">策略</option>
              <option value="method">方法</option>
              <option value="error_pattern">错误模式</option>
              <option value="tool_usage">工具使用</option>
              <option value="context_handling">上下文处理</option>
            </select>
          </div>

          <div className="form-group">
            <label>标题</label>
            <input
              type="text"
              value={formData.title}
              onChange={(e) => setFormData({ ...formData, title: e.target.value })}
              required
              maxLength={200}
            />
          </div>

          <div className="form-group">
            <label>内容</label>
            <textarea
              value={formData.content}
              onChange={(e) => setFormData({ ...formData, content: e.target.value })}
              required
              rows={6}
            />
          </div>

          <div className="form-group">
            <label>触发条件</label>
            <textarea
              value={formData.trigger_conditions}
              onChange={(e) => setFormData({ ...formData, trigger_conditions: e.target.value })}
              required
              rows={3}
            />
          </div>

          <div className="form-group">
            <label>置信度</label>
            <div className="confidence-input">
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={formData.confidence}
                onChange={(e) => setFormData({ ...formData, confidence: Number(e.target.value) })}
              />
              <span>{(formData.confidence * 100).toFixed(0)}%</span>
            </div>
          </div>

          <div className="form-group">
            <label>来源任务</label>
            <input
              type="text"
              value={formData.source_task}
              onChange={(e) => setFormData({ ...formData, source_task: e.target.value })}
            />
          </div>

          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>
              取消
            </button>
            <button type="submit" className="btn-primary">
              保存
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default ExperienceModal
