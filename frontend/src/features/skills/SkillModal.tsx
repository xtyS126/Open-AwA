import { useState, useRef, useEffect } from 'react'
import { skillsAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import styles from './SkillModal.module.css'

interface SkillModalProps {
  onClose: () => void
  onSuccess: () => void
}

interface FormErrors {
  name?: string
  description?: string
  instructions?: string
}

export default function SkillModal({ onClose, onSuccess }: SkillModalProps) {
  const [file, setFile] = useState<File | null>(null)
  const [skillType, setSkillType] = useState('global')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [instructions, setInstructions] = useState('')
  const [loading, setLoading] = useState(false)
  const [errors, setErrors] = useState<FormErrors>({})
  const fileInputRef = useRef<HTMLInputElement>(null)
  const nameInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    nameInputRef.current?.focus()
  }, [])

  const validateForm = (): boolean => {
    const newErrors: FormErrors = {}

    if (!name.trim()) {
      newErrors.name = '技能名称不能为空'
    } else if (name.length > 50) {
      newErrors.name = '技能名称不能超过50个字符'
    }

    if (!description.trim()) {
      newErrors.description = '描述不能为空'
    } else if (description.length > 200) {
      newErrors.description = '描述不能超过200个字符'
    }

    if (!instructions.trim()) {
      newErrors.instructions = '指令不能为空'
    } else if (instructions.length < 10) {
      newErrors.instructions = '指令内容过于简单，请提供更详细的描述'
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selectedFile = e.target.files[0]
      setFile(selectedFile)

      try {
        setLoading(true)
        const response = await skillsAPI.parseUpload(selectedFile)
        const data = response.data
        if (data.name) setName(data.name)
        if (data.description) setDescription(data.description)
        if (data.instructions) setInstructions(data.instructions)

        appLogger.info({
          event: 'skill_file_parsed',
          module: 'skills',
          action: 'parse_upload',
          message: 'skill file parsed',
          status: 'success',
          extra: { file_name: selectedFile.name },
        })
      } catch (error) {
        console.error('Failed to parse file:', error)
        appLogger.error({
          event: 'skill_file_parse_failed',
          module: 'skills',
          action: 'parse_upload',
          message: 'skill file parse failed',
          status: 'failure',
          extra: { error: error instanceof Error ? error.message : String(error) },
        })
      } finally {
        setLoading(false)
      }
    }
  }

  const handleSubmit = async () => {
    if (!validateForm()) {
      appLogger.warning({
        event: 'skill_create_validation_failed',
        module: 'skills',
        action: 'create_skill',
        message: 'skill validation failed',
        status: 'validation_error',
      })
      return
    }

    try {
      setLoading(true)
      const config = `name: ${name}\ndescription: ${description}\ninstructions: |\n  ${instructions.split('\n').join('\n  ')}\ntype: ${skillType}`

      await skillsAPI.install({
        name,
        version: '1.0.0',
        description,
        config
      })

      appLogger.info({
        event: 'skill_create_success',
        module: 'skills',
        action: 'create_skill',
        message: 'skill created',
        status: 'success',
        extra: { skill_name: name, skill_type: skillType },
      })

      onSuccess()
    } catch (error) {
      console.error('Failed to create skill:', error)
      appLogger.error({
        event: 'skill_create_failed',
        module: 'skills',
        action: 'create_skill',
        message: 'skill create failed',
        status: 'failure',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose()
    }
  }

  return (
    <div
      className={styles['modal-overlay']}
      onClick={(e) => e.target === e.currentTarget && onClose()}
      onKeyDown={handleKeyDown}
      role="dialog"
      aria-modal="true"
      aria-labelledby="skill-modal-title"
    >
      <div className={`${styles['modal-content']} ${styles['skill-modal']}`}>
        <div className={styles['modal-header']}>
          <h2 id="skill-modal-title">创建技能</h2>
          <button
            className={styles['close-btn']}
            onClick={onClose}
            aria-label="关闭"
          >
            &times;
          </button>
        </div>

        <div className={styles['modal-body']}>
          <div
            className={styles['upload-area']}
            onClick={() => fileInputRef.current?.click()}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
            aria-label="上传文件"
          >
            <input
              type="file"
              ref={fileInputRef}
              style={{ display: 'none' }}
              accept=".zip,.skill,.md,.yaml,.yml"
              onChange={handleFileChange}
            />
            <div className={styles['upload-icon']} aria-hidden="true">+</div>
            <p className={styles['upload-title']}>
              {file ? file.name : '上传文件自动解析'}
            </p>
            <p className={styles['upload-desc']}>
              支持 .zip、.skill、.md、.yaml 格式，包含 SKILL.md 配置文件
            </p>
          </div>

          <div className={styles['form-section']}>
            <h3 className={styles['section-title']}>基本信息</h3>

            <div className={styles['form-group']}>
              <label htmlFor="skill-name">
                <span className={styles['required']}>*</span>技能名称
              </label>
              <input
                id="skill-name"
                ref={nameInputRef}
                type="text"
                value={name}
                onChange={(e) => {
                  setName(e.target.value)
                  if (errors.name) setErrors({ ...errors, name: undefined })
                }}
                placeholder="例如：代码分析助手"
                aria-invalid={!!errors.name}
                aria-describedby={errors.name ? 'skill-name-error' : undefined}
              />
              {errors.name && (
                <span id="skill-name-error" className={styles['error-text']} role="alert">
                  {errors.name}
                </span>
              )}
            </div>

            <div className={styles['form-group']}>
              <label htmlFor="skill-description">
                <span className={styles['required']}>*</span>描述
              </label>
              <input
                id="skill-description"
                type="text"
                value={description}
                onChange={(e) => {
                  setDescription(e.target.value)
                  if (errors.description) setErrors({ ...errors, description: undefined })
                }}
                placeholder="描述技能的用途和使用场景"
                aria-invalid={!!errors.description}
                aria-describedby={errors.description ? 'skill-description-error' : undefined}
              />
              {errors.description && (
                <span id="skill-description-error" className={styles['error-text']} role="alert">
                  {errors.description}
                </span>
              )}
            </div>

            <div className={styles['form-group']}>
              <label>技能类型</label>
              <div className={styles['radio-group']} role="radiogroup" aria-label="技能类型">
                <label className={styles['radio-label']}>
                  <input
                    type="radio"
                    value="global"
                    checked={skillType === 'global'}
                    onChange={(e) => setSkillType(e.target.value)}
                  />
                  <span>全局</span>
                </label>
                <label className={styles['radio-label']}>
                  <input
                    type="radio"
                    value="project"
                    checked={skillType === 'project'}
                    onChange={(e) => setSkillType(e.target.value)}
                  />
                  <span>项目</span>
                </label>
              </div>
            </div>
          </div>

          <div className={`${styles['form-section']} ${styles['flex-1']}`}>
            <h3 className={styles['section-title']}>指令配置</h3>

            <div className={`${styles['form-group']} ${styles['flex-1']}`}>
              <label htmlFor="skill-instructions">
                <span className={styles['required']}>*</span>指令
              </label>
              <textarea
                id="skill-instructions"
                value={instructions}
                onChange={(e) => {
                  setInstructions(e.target.value)
                  if (errors.instructions) setErrors({ ...errors, instructions: undefined })
                }}
                placeholder="# 技能名称&#10;## 使用场景&#10;## 行为规则&#10;## 输出格式"
                aria-invalid={!!errors.instructions}
                aria-describedby={errors.instructions ? 'skill-instructions-error' : undefined}
              />
              {errors.instructions && (
                <span id="skill-instructions-error" className={styles['error-text']} role="alert">
                  {errors.instructions}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className={styles['modal-footer']}>
          <button
            className={`btn ${styles['btn-secondary']}`}
            onClick={onClose}
            disabled={loading}
            aria-label="取消创建"
          >
            取消
          </button>
          <button
            className="btn btn-primary"
            onClick={handleSubmit}
            disabled={loading}
            aria-label="确认创建"
          >
            {loading ? '处理中...' : '创建'}
          </button>
        </div>
      </div>
    </div>
  )
}
