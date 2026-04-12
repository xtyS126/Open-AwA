import { useState, useRef } from 'react'
import { skillsAPI } from '@/shared/api/api'
import { appLogger } from '@/shared/utils/logger'
import styles from './SkillModal.module.css'

interface SkillModalProps {
  onClose: () => void
  onSuccess: () => void
}

export default function SkillModal({ onClose, onSuccess }: SkillModalProps) {
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [instructions, setInstructions] = useState('')
  const [loading, setLoading] = useState(false)
  const [step, setStep] = useState(1)
  const [parseError, setParseError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selectedFile = e.target.files[0]
      setFile(selectedFile)
      setParseError('')

      try {
        setLoading(true)
        const response = await skillsAPI.parseUpload(selectedFile)
        const data = response.data
        if (data.name) setName(data.name)
        if (data.description) setDescription(data.description)
        if (data.instructions) setInstructions(data.instructions)
        appLogger.info({
          event: 'skill_create_file_parsed',
          module: 'skills',
          action: 'parse_upload',
          status: 'success',
          message: '技能文件解析成功',
        })
        // 解析成功后自动进入下一步
        setStep(2)
      } catch (error) {
        setParseError('文件解析失败，请手动填写信息')
        appLogger.error({
          event: 'skill_create_file_parse_failed',
          module: 'skills',
          action: 'parse_upload',
          status: 'failure',
          message: '技能文件解析失败',
          extra: { error: error instanceof Error ? error.message : String(error) },
        })
      } finally {
        setLoading(false)
      }
    }
  }

  const handleSubmit = async () => {
    if (!name.trim() || !description.trim() || !instructions.trim()) {
      return
    }

    try {
      setLoading(true)
      appLogger.info({
        event: 'skill_create_submit',
        module: 'skills',
        action: 'create',
        status: 'start',
        message: '开始创建技能',
        extra: { name },
      })
      const config = `name: ${name}\ndescription: ${description}\ninstructions: |\n  ${instructions.split('\n').join('\n  ')}\ntype: global`
      
      await skillsAPI.install({
        name,
        version: '1.0.0',
        description,
        config
      })
      appLogger.info({
        event: 'skill_create_submit',
        module: 'skills',
        action: 'create',
        status: 'success',
        message: '技能创建成功',
        extra: { name },
      })
      onSuccess()
    } catch (error) {
      appLogger.error({
        event: 'skill_create_submit',
        module: 'skills',
        action: 'create',
        status: 'failure',
        message: '创建技能失败',
        extra: { error: error instanceof Error ? error.message : String(error) },
      })
      alert('创建技能失败')
    } finally {
      setLoading(false)
    }
  }

  const canProceedToStep2 = name.trim() && description.trim()
  const canSubmit = name.trim() && description.trim() && instructions.trim()

  return (
    <div className={styles['modal-overlay']}>
      <div className={`${styles['modal-content']} ${styles['skill-modal']}`}>
        <div className={styles['modal-header']}>
          <h2>创建技能</h2>
          <button className={styles['close-btn']} onClick={onClose}>&times;</button>
        </div>

        {/* 步骤指示器 */}
        <div className={styles['step-indicator']}>
          <div className={`${styles['step-item']} ${step >= 1 ? styles['step-active'] : ''}`}>
            <span className={styles['step-number']}>1</span>
            <span className={styles['step-label']}>导入或填写</span>
          </div>
          <div className={styles['step-divider']} />
          <div className={`${styles['step-item']} ${step >= 2 ? styles['step-active'] : ''}`}>
            <span className={styles['step-number']}>2</span>
            <span className={styles['step-label']}>编写指令</span>
          </div>
          <div className={styles['step-divider']} />
          <div className={`${styles['step-item']} ${step >= 3 ? styles['step-active'] : ''}`}>
            <span className={styles['step-number']}>3</span>
            <span className={styles['step-label']}>确认创建</span>
          </div>
        </div>
        
        <div className={styles['modal-body']}>
          {step === 1 && (
            <>
              <div 
                className={styles['upload-area']} 
                onClick={() => fileInputRef.current?.click()}
              >
                <input 
                  type="file" 
                  ref={fileInputRef} 
                  style={{ display: 'none' }} 
                  accept=".zip,.skill,.md,.yaml,.yml"
                  onChange={handleFileChange}
                />
                <div className={styles['upload-icon']}>
                  {file ? file.name : '点击上传文件'}
                </div>
                <p className={styles['upload-desc']}>支持 .zip / .skill / .md / .yaml 格式，上传后自动解析</p>
              </div>

              {parseError && (
                <div className={styles['parse-error']}>{parseError}</div>
              )}

              <div className={styles['form-group']}>
                <label><span className={styles['required']}>*</span> 技能名称</label>
                <input 
                  type="text" 
                  value={name} 
                  onChange={(e) => setName(e.target.value)} 
                  placeholder="简短名称，例如：codemap"
                />
              </div>

              <div className={styles['form-group']}>
                <label><span className={styles['required']}>*</span> 描述</label>
                <input 
                  type="text" 
                  value={description} 
                  onChange={(e) => setDescription(e.target.value)} 
                  placeholder="描述触发场景，例如：分析代码库结构、依赖关系"
                />
              </div>
            </>
          )}

          {step === 2 && (
            <div className={`${styles['form-group']} ${styles['flex-1']}`}>
              <label><span className={styles['required']}>*</span> 指令内容</label>
              <textarea 
                value={instructions} 
                onChange={(e) => setInstructions(e.target.value)} 
                placeholder={'当技能被触发时模型需遵循的规则，例如：\n\n# codemap\n## 命令\n## 使用场景\n## 输出格式'}
              />
            </div>
          )}

          {step === 3 && (
            <div className={styles['review-section']}>
              <div className={styles['review-item']}>
                <span className={styles['review-label']}>名称</span>
                <span className={styles['review-value']}>{name}</span>
              </div>
              <div className={styles['review-item']}>
                <span className={styles['review-label']}>描述</span>
                <span className={styles['review-value']}>{description}</span>
              </div>
              <div className={styles['review-item']}>
                <span className={styles['review-label']}>指令</span>
                <pre className={styles['review-instructions']}>{instructions}</pre>
              </div>
            </div>
          )}
        </div>

        <div className={styles['modal-footer']}>
          {step > 1 && (
            <button 
              className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} 
              onClick={() => setStep(step - 1)} 
              disabled={loading}
            >
              上一步
            </button>
          )}
          <button className={`btn ${styles['btn-secondary'] || 'btn-secondary'}`} onClick={onClose} disabled={loading}>
            取消
          </button>
          {step < 3 ? (
            <button 
              className={`btn btn-primary`} 
              onClick={() => setStep(step + 1)} 
              disabled={step === 1 ? !canProceedToStep2 : !canSubmit}
            >
              下一步
            </button>
          ) : (
            <button className={`btn btn-primary`} onClick={handleSubmit} disabled={loading || !canSubmit}>
              {loading ? '创建中...' : '确认创建'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
