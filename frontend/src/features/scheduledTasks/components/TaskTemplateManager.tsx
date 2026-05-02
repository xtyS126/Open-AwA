/**
 * 任务模板管理器组件。
 * 支持将当前任务配置保存为模板，以及从模板快速加载配置。
 * 模板数据存储在 localStorage 中。
 */
import { useState, useCallback } from 'react'
import { Save, Bookmark, Trash2, Copy } from 'lucide-react'
import styles from './TaskTemplateManager.module.css'

export interface TaskTemplate {
  id: string
  name: string
  createdAt: string
  config: Record<string, unknown>
}

interface Props {
  currentConfig: Record<string, unknown>
  onLoad: (config: Record<string, unknown>) => void
}

const STORAGE_KEY = 'scheduled_task_templates'

function loadTemplates(): TaskTemplate[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    return JSON.parse(raw) as TaskTemplate[]
  } catch {
    return []
  }
}

function saveTemplates(templates: TaskTemplate[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(templates))
}

export function useTaskTemplates() {
  const [templates, setTemplates] = useState<TaskTemplate[]>(loadTemplates)

  const saveTemplate = useCallback(
    (name: string, config: Record<string, unknown>) => {
      const template: TaskTemplate = {
        id: `tpl_${Date.now()}`,
        name,
        createdAt: new Date().toISOString(),
        config,
      }
      const next = [template, ...templates]
      setTemplates(next)
      saveTemplates(next)
    },
    [templates]
  )

  const deleteTemplate = useCallback(
    (id: string) => {
      const next = templates.filter((t) => t.id !== id)
      setTemplates(next)
      saveTemplates(next)
    },
    [templates]
  )

  return { templates, saveTemplate, deleteTemplate }
}

export default function TaskTemplateManager({
  currentConfig,
  onLoad,
}: Props) {
  const { templates, saveTemplate, deleteTemplate } = useTaskTemplates()
  const [saveName, setSaveName] = useState('')
  const [showSave, setShowSave] = useState(false)

  const handleSave = () => {
    const name = saveName.trim()
    if (!name) return
    saveTemplate(name, currentConfig)
    setSaveName('')
    setShowSave(false)
  }

  return (
    <div className={styles['container']}>
      <div className={styles['header']}>
        <Bookmark size={16} />
        <span>任务模板</span>
        <button
          className={styles['save-btn']}
          type="button"
          onClick={() => setShowSave(!showSave)}
        >
          <Save size={14} />
          保存当前
        </button>
      </div>

      {showSave && (
        <div className={styles['save-form']}>
          <input
            type="text"
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSave()}
            placeholder="输入模板名称..."
            className={styles['save-input']}
            autoFocus
          />
          <button className={styles['save-confirm']} type="button" onClick={handleSave}>
            保存
          </button>
        </div>
      )}

      {templates.length === 0 ? (
        <div className={styles['empty']}>
          <span>暂无模板，保存当前配置为模板以便快速复用</span>
        </div>
      ) : (
        <div className={styles['template-list']}>
          {templates.map((tpl) => (
            <div key={tpl.id} className={styles['template-item']}>
              <div className={styles['template-info']}>
                <span className={styles['template-name']}>{tpl.name}</span>
                <span className={styles['template-date']}>
                  {new Date(tpl.createdAt).toLocaleDateString('zh-CN')}
                </span>
              </div>
              <div className={styles['template-actions']}>
                <button
                  type="button"
                  className={styles['template-action']}
                  title="加载模板"
                  onClick={() => onLoad(tpl.config)}
                >
                  <Copy size={14} />
                </button>
                <button
                  type="button"
                  className={styles['template-action-danger']}
                  title="删除模板"
                  onClick={() => {
                    if (confirm(`确定删除模板 "${tpl.name}" 吗？`)) {
                      deleteTemplate(tpl.id)
                    }
                  }}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
