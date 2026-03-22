import { Experience } from '../services/experiencesApi'

interface Props {
  experience: Experience
  typeColor: string
  typeLabel: string
  onEdit: () => void
  onDelete: () => void
}

function ExperienceCard({ experience, typeColor, typeLabel, onEdit, onDelete }: Props) {
  const successRate = experience.usage_count > 0
    ? (experience.success_count / experience.usage_count * 100).toFixed(1)
    : '0.0'

  return (
    <div className="experience-card">
      <div className="card-header">
        <span className={`type-badge ${typeColor}`}>{typeLabel}</span>
        <div className="card-actions">
          <button onClick={onEdit} className="btn-icon" title="编辑">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
          </button>
          <button onClick={onDelete} className="btn-icon btn-danger" title="删除">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="3 6 5 6 21 6"/>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
            </svg>
          </button>
        </div>
      </div>

      <h3 className="card-title">{experience.title}</h3>
      <p className="card-content">{experience.content}</p>

      <div className="card-trigger">
        <strong>触发条件：</strong>
        {experience.trigger_conditions}
      </div>

      <div className="card-stats">
        <div className="stat">
          <span className="stat-label">置信度</span>
          <span className="stat-value">{(experience.confidence * 100).toFixed(0)}%</span>
        </div>
        <div className="stat">
          <span className="stat-label">成功率</span>
          <span className="stat-value">{successRate}%</span>
        </div>
        <div className="stat">
          <span className="stat-label">使用次数</span>
          <span className="stat-value">{experience.usage_count}</span>
        </div>
      </div>

      <div className="card-footer">
        <span className="source">来源：{experience.source_task}</span>
        <span className="date">
          {new Date(experience.created_at).toLocaleDateString()}
        </span>
      </div>
    </div>
  )
}

export default ExperienceCard
