import { useState, useEffect } from 'react'
import { skillsAPI } from '../services/api'
import './SkillsPage.css'

function SkillsPage() {
  const [skills, setSkills] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadSkills()
  }, [])

  const loadSkills = async () => {
    try {
      const response = await skillsAPI.getAll()
      setSkills(response.data)
    } catch (error) {
      throw error
    } finally {
      setLoading(false)
    }
  }

  const handleToggle = async (id: string) => {
    try {
      await skillsAPI.toggle(id)
      loadSkills()
    } catch (error) {
      throw error
    }
  }

  const handleUninstall = async (id: string) => {
    if (!confirm('确定要卸载这个技能吗？')) return
    try {
      await skillsAPI.uninstall(id)
      loadSkills()
    } catch (error) {
      throw error
    }
  }

  if (loading) {
    return <div className="loading">加载中...</div>
  }

  return (
    <div className="skills-page">
      <div className="page-header">
        <h1>技能管理</h1>
        <button className="btn btn-primary">浏览市场</button>
      </div>

      <div className="skills-grid">
        {skills.length === 0 ? (
          <div className="empty-state">
            <p>还没有安装任何技能</p>
            <button className="btn btn-secondary">浏览市场</button>
          </div>
        ) : (
          skills.map((skill) => (
            <div key={skill.id} className="skill-card">
              <div className="skill-header">
                <h3>{skill.name}</h3>
                <span className="skill-version">v{skill.version || '1.0.0'}</span>
              </div>
              <p className="skill-desc">{skill.description || '暂无描述'}</p>
              <div className="skill-actions">
                <button
                  className={`btn ${skill.enabled ? 'btn-secondary' : 'btn-primary'}`}
                  onClick={() => handleToggle(skill.id)}
                >
                  {skill.enabled ? '禁用' : '启用'}
                </button>
                <button
                  className="btn btn-danger"
                  onClick={() => handleUninstall(skill.id)}
                >
                  卸载
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

export default SkillsPage
