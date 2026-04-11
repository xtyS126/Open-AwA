import { useCallback, useEffect, useState } from 'react'
import { skillsAPI } from '@/shared/api/api'
import { Skill } from '@/features/dashboard/dashboard'
import SkillModal from '@/features/skills/SkillModal'
import { appLogger } from '@/shared/utils/logger'
import styles from './SkillsPage.module.css'

function getErrorMessage(error: unknown, fallback: string): string {
  const maybeError = error as { response?: { data?: { detail?: string } } }
  const detail = maybeError?.response?.data?.detail
  return typeof detail === 'string' && detail.trim() ? detail : fallback
}

function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState(true)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [pendingSkillId, setPendingSkillId] = useState<string | null>(null)

  const loadSkills = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const response = await skillsAPI.getAll()
      setSkills(response.data)
    } catch (error) {
      appLogger.error({
        event: 'skills_page_load_failed',
        module: 'skills',
        action: 'load',
        status: 'failure',
        message: '加载技能列表失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      setSkills([])
      setLoadError(getErrorMessage(error, '加载技能列表失败，请稍后重试'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadSkills()
  }, [loadSkills])

  const handleToggle = async (id: string) => {
    setActionError(null)
    setPendingSkillId(id)
    try {
      await skillsAPI.toggle(id)
      await loadSkills()
    } catch (error) {
      appLogger.error({
        event: 'skills_page_toggle_failed',
        module: 'skills',
        action: 'toggle',
        status: 'failure',
        message: '切换技能状态失败',
        extra: { skill_id: id, error: error instanceof Error ? error.message : String(error) },
      })
      setActionError(getErrorMessage(error, '切换技能状态失败，请稍后重试'))
    } finally {
      setPendingSkillId(null)
    }
  }

  const handleUninstall = async (id: string) => {
    if (!confirm('确定要卸载这个技能吗？')) return
    setActionError(null)
    setPendingSkillId(id)
    try {
      await skillsAPI.uninstall(id)
      await loadSkills()
    } catch (error) {
      appLogger.error({
        event: 'skills_page_uninstall_failed',
        module: 'skills',
        action: 'uninstall',
        status: 'failure',
        message: '卸载技能失败',
        extra: { skill_id: id, error: error instanceof Error ? error.message : String(error) },
      })
      setActionError(getErrorMessage(error, '卸载技能失败，请稍后重试'))
    } finally {
      setPendingSkillId(null)
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
          <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={() => void loadSkills()} disabled={loading}>
            刷新列表
          </button>
          <button className={`btn btn-primary`} onClick={() => setIsModalOpen(true)}>创建技能</button>
          <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`}>浏览市场</button>
        </div>
      </div>

      {loadError && (
        <div className={styles['status-message-error']}>
          {loadError}
        </div>
      )}
      {actionError && (
        <div className={styles['status-message-error']}>
          {actionError}
        </div>
      )}

      <div className={styles['skills-grid']}>
        {skills.length === 0 ? (
          <div className={styles['empty-state']}>
            <p>{loadError ? '技能列表暂时不可用' : '还没有安装任何技能'}</p>
            {loadError && (
              <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={() => void loadSkills()}>
                重试加载
              </button>
            )}
            {!loadError && (
              <button className={`btn btn-primary`} onClick={() => setIsModalOpen(true)}>创建技能</button>
            )}
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
                  onClick={() => void handleToggle(skill.id)}
                  disabled={pendingSkillId === skill.id}
                >
                  {pendingSkillId === skill.id ? '处理中...' : skill.enabled ? '禁用' : '启用'}
                </button>
                <button
                  className={`btn ${styles['btn-danger'] || 'btn-danger'}`}
                  onClick={() => void handleUninstall(skill.id)}
                  disabled={pendingSkillId === skill.id}
                >
                  {pendingSkillId === skill.id ? '处理中...' : '卸载'}
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
            void loadSkills()
          }} 
        />
      )}
    </div>
  )
}

export default SkillsPage
