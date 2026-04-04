import { useState, useEffect } from 'react'
import { skillsAPI } from '@/shared/api/api'
import { Skill } from '@/features/dashboard/dashboard'
import SkillModal from '@/features/skills/SkillModal'
import styles from './SkillsPage.module.css'

function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState(true)
  const [isModalOpen, setIsModalOpen] = useState(false)

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
    return <div className={styles['loading']}>加载中...</div>
  }

  return (
    <div className={styles['skills-page']}>
      <div className={styles['page-header']}>
        <h1>技能管理</h1>
        <div style={{ display: 'flex', gap: '10px' }}>
          <button className={`btn btn-primary`} onClick={() => setIsModalOpen(true)}>创建技能</button>
          <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}>浏览市场</button>
        </div>
      </div>

      <div className={styles['skills-grid']}>
        {skills.length === 0 ? (
          <div className={styles['empty-state']}>
            <p>还没有安装任何技能</p>
            <button className={`btn btn-primary`} onClick={() => setIsModalOpen(true)}>创建技能</button>
          </div>
        ) : (
          skills.map((skill) => (
            <div key={skill.id} className={styles['skill-card']}>
              <div className={styles['skill-header']}>
                <h3>{skill.name}</h3>
                <span className={styles['skill-version']}>v{skill.version || '1.0.0'}</span>
              </div>
              <p className={styles['skill-desc']}>{skill.description || '暂无描述'}</p>
              <div className={styles['skill-actions']}>
                <button
                  className={`btn ${skill.enabled ? styles['btn-secondary'] : styles['btn-primary']}`}
                  onClick={() => handleToggle(skill.id)}
                >
                  {skill.enabled ? '禁用' : '启用'}
                </button>
                <button
                  className={`btn ${styles['btn-danger'] || 'btn-danger'}`}
                  onClick={() => handleUninstall(skill.id)}
                >
                  卸载
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {isModalOpen && (
        <SkillModal 
          onClose={() => setIsModalOpen(false)} 
          onSuccess={() => {
            setIsModalOpen(false)
            loadSkills()
          }} 
        />
      )}
    </div>
  )
}

export default SkillsPage
