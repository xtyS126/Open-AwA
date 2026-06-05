/**
 * Agent 创建/编辑模态框。
 * 支持配置 Agent 名称、类型、系统提示、工具开关、模型等。
 */
import React, { useState } from 'react'
import { X } from 'lucide-react'
import styles from './AgentCreateModal.module.css'

interface AgentInfo {
  name: string
  type: string
  description: string
  system_prompt?: string
  tools?: string[]
  model?: string
}

interface AgentCreateModalProps {
  agent: AgentInfo | null
  onClose: () => void
}

const AGENT_TYPES = [
  { value: 'Explore', label: '探索 (Explore)', desc: '只读代码搜索和调研' },
  { value: 'Plan', label: '规划 (Plan)', desc: '仅只读规划分析' },
  { value: 'general-purpose', label: '通用 (General)', desc: '完整读写能力' },
]

const AVAILABLE_TOOLS = [
  'file_read', 'file_write', 'file_search', 'command_execute',
  'web_search', 'web_fetch', 'memory_search', 'memory_write',
  'skill_execute', 'plugin_invoke', 'mcp_invoke',
]

const AgentCreateModal: React.FC<AgentCreateModalProps> = ({ agent, onClose }) => {
  const isEdit = agent !== null
  const [name, setName] = useState(agent?.name || '')
  const [type, setType] = useState(agent?.type || 'Explore')
  const [description, setDescription] = useState(agent?.description || '')
  const [systemPrompt, setSystemPrompt] = useState(agent?.system_prompt || '')
  const [selectedTools, setSelectedTools] = useState<string[]>(agent?.tools || [])
  const [model, setModel] = useState(agent?.model || '')
  const [saving, setSaving] = useState(false)

  const toggleTool = (tool: string) => {
    setSelectedTools((prev) =>
      prev.includes(tool) ? prev.filter((t) => t !== tool) : [...prev, tool]
    )
  }

  const handleSave = async () => {
    if (!name.trim()) return
    setSaving(true)
    try {
      // 将 Agent 配置持久化到 localStorage（后续可通过后端 API 扩展）
      const customAgents = JSON.parse(localStorage.getItem('openawa_custom_agents') || '{}')
      customAgents[name.trim()] = {
        name: name.trim(),
        type,
        description,
        system_prompt: systemPrompt,
        tools: selectedTools,
        model: model || undefined,
        updated_at: new Date().toISOString(),
      }
      localStorage.setItem('openawa_custom_agents', JSON.stringify(customAgents))
      onClose()
    } catch {
      // ignore
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.header}>
          <h2>{isEdit ? '编辑 Agent' : '创建 Agent'}</h2>
          <button className={styles.closeBtn} onClick={onClose}><X size={18} /></button>
        </div>

        <div className={styles.body}>
          <div className={styles.field}>
            <label>名称</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="输入 Agent 名称"
              className={styles.input}
            />
          </div>

          <div className={styles.field}>
            <label>类型</label>
            <div className={styles.typeSelector}>
              {AGENT_TYPES.map((t) => (
                <div
                  key={t.value}
                  className={`${styles.typeOption} ${type === t.value ? styles.typeActive : ''}`}
                  onClick={() => setType(t.value)}
                >
                  <span className={styles.typeLabel}>{t.label}</span>
                  <span className={styles.typeDesc}>{t.desc}</span>
                </div>
              ))}
            </div>
          </div>

          <div className={styles.field}>
            <label>描述</label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="简要描述 Agent 的用途"
              className={styles.input}
            />
          </div>

          <div className={styles.field}>
            <label>系统提示词</label>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="设定 Agent 的角色、能力和行为规则..."
              className={styles.textarea}
              rows={5}
            />
          </div>

          <div className={styles.field}>
            <label>可用工具</label>
            <div className={styles.toolGrid}>
              {AVAILABLE_TOOLS.map((tool) => (
                <label key={tool} className={styles.toolCheckbox}>
                  <input
                    type="checkbox"
                    checked={selectedTools.includes(tool)}
                    onChange={() => toggleTool(tool)}
                  />
                  <span>{tool}</span>
                </label>
              ))}
            </div>
          </div>

          <div className={styles.field}>
            <label>模型</label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="默认模型（留空使用系统默认）"
              className={styles.input}
            />
          </div>
        </div>

        <div className={styles.footer}>
          <button className={styles.cancelBtn} onClick={onClose}>取消</button>
          <button
            className={styles.saveBtn}
            onClick={handleSave}
            disabled={!name.trim() || saving}
          >
            {saving ? '保存中...' : isEdit ? '更新' : '创建'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default React.memo(AgentCreateModal)
