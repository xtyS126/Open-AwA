import { useState, useRef } from 'react'
import { skillsAPI } from '@/shared/api/api'
import styles from './SkillModal.module.css'

interface SkillModalProps {
  onClose: () => void
  onSuccess: () => void
}

export default function SkillModal({ onClose, onSuccess }: SkillModalProps) {
  const [file, setFile] = useState<File | null>(null)
  const [skillType, setSkillType] = useState('global')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [instructions, setInstructions] = useState('')
  const [loading, setLoading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const selectedFile = e.target.files[0]
      setFile(selectedFile)
      
      // Auto parse

      try {
        setLoading(true)
        const response = await skillsAPI.parseUpload(selectedFile)
        const data = response.data
        if (data.name) setName(data.name)
        if (data.description) setDescription(data.description)
        if (data.instructions) setInstructions(data.instructions)
      } catch (error) {
        console.error('Failed to parse file:', error)
      } finally {
        setLoading(false)
      }
    }
  }

  const handleSubmit = async () => {
    if (!name || !description || !instructions) {
      alert('请填写完整信息')
      return
    }

    try {
      setLoading(true)
      // Create YAML config
      const config = `name: ${name}\ndescription: ${description}\ninstructions: |\n  ${instructions.split('\n').join('\n  ')}\ntype: ${skillType}`
      
      await skillsAPI.install({
        name,
        version: '1.0.0',
        description,
        config
      })
      onSuccess()
    } catch (error) {
      console.error('Failed to create skill:', error)
      alert('创建技能失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles['modal-overlay']}>
      <div className={`${styles['modal-content']} ${styles['skill-modal']}`}>
        <div className={styles['modal-header']}>
          <h2>创建技能</h2>
          <button className={styles['close-btn']} onClick={onClose}>&times;</button>
        </div>
        
        <div className={styles['modal-body']}>
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
            <div className={styles['upload-icon']}>文件</div>
            <p className={styles['upload-title']}>{file ? file.name : '上传进行智能解析'}</p>
            <p className={styles['upload-desc']}>包含 SKILL.md 文件的 .zip 或 .skill 文件，SKILL.md 位于根目录，包含 YAML 格式的技能名称和描述。</p>
          </div>

          <div className={styles['form-group']}>
            <label><span className={styles['required']}>*</span>技能类型</label>
            <div className={styles['radio-group']}>
              <label>
                <input 
                  type="radio" 
                  value="global" 
                  checked={skillType === 'global'} 
                  onChange={(e) => setSkillType(e.target.value)} 
                /> 全局
              </label>
              <label>
                <input 
                  type="radio" 
                  value="project" 
                  checked={skillType === 'project'} 
                  onChange={(e) => setSkillType(e.target.value)} 
                /> 项目
              </label>
            </div>
          </div>

          <div className={styles['form-group']}>
            <label><span className={styles['required']}>*</span>技能名称</label>
            <input 
              type="text" 
              value={name} 
              onChange={(e) => setName(e.target.value)} 
              placeholder="为这个 Skill 起一个简短的名称，例如：codemap"
            />
          </div>

          <div className={styles['form-group']}>
            <label><span className={styles['required']}>*</span>描述</label>
            <input 
              type="text" 
              value={description} 
              onChange={(e) => setDescription(e.target.value)} 
              placeholder="简单描述这个 Skill 应该在什么情况下被触发，例如：分析代码库结构、依赖关系和变更"
            />
          </div>

          <div className={`${styles['form-group']} ${styles['flex-1']}`}>
            <label><span className={styles['required']}>*</span>指令</label>
            <textarea 
              value={instructions} 
              onChange={(e) => setInstructions(e.target.value)} 
              placeholder="当这个 Skill 被触发时，你希望模型遵循哪些规则或信息，例如：&#10;&#10;# codemap&#10;## 命令&#10;## 使用场景&#10;## 输出解释&#10;## 示例"
            />
          </div>
        </div>

        <div className={styles['modal-footer']}>
          <button className={`${styles['btn']} ${styles['btn-secondary']}`} onClick={onClose} disabled={loading}>取消</button>
          <button className={`${styles['btn']} ${styles['btn-primary']}`} onClick={handleSubmit} disabled={loading}>
            {loading ? styles['处理中...'] : styles['确认']}
          </button>
        </div>
      </div>
    </div>
  )
}
