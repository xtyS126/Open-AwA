/**
 * Agent 管理页面 — 列出所有已注册的 Agent 类型，支持创建、编辑、删除。
 */
import React, { useEffect, useState, useCallback } from 'react'
import { Plus, Edit, Trash2, Copy, Play, Zap, Eye, Wrench } from 'lucide-react'
import { subagentsApi } from '@/shared/api/subagentsApi'
import AgentCreateModal from './components/AgentCreateModal'
import styles from './AgentListPage.module.css'

interface AgentInfo {
  name: string
  type: string
  description: string
  system_prompt?: string
  tools?: string[]
  model?: string
}

const AGENT_TYPE_ICONS: Record<string, React.FC<{ size?: number }>> = {
  Explore: Eye,
  Plan: Zap,
  'general-purpose': Wrench,
}

const AGENT_TYPE_COLORS: Record<string, string> = {
  Explore: '#3b82f6',
  Plan: '#f59e0b',
  'general-purpose': '#22c55e',
}

const AgentListPage: React.FC = () => {
  const [agents, setAgents] = useState<AgentInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [editingAgent, setEditingAgent] = useState<AgentInfo | null>(null)

  const loadAgents = useCallback(async () => {
    setLoading(true)
    try {
      const data = await subagentsApi.listAgents()
      setAgents(data.agents || [])
    } catch {
      setAgents([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadAgents()
  }, [loadAgents])

  const handleCreate = useCallback(() => {
    setEditingAgent(null)
    setShowCreate(true)
  }, [])

  const handleEdit = useCallback((agent: AgentInfo) => {
    setEditingAgent(agent)
    setShowCreate(true)
  }, [])

  const handleClose = useCallback(() => {
    setShowCreate(false)
    setEditingAgent(null)
    loadAgents()
  }, [loadAgents])

  const TypeIcon = (type: string) => {
    const Icon = AGENT_TYPE_ICONS[type] || Zap
    return <Icon size={16} />
  }

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1>Agent 管理</h1>
        <button className={styles.createBtn} onClick={handleCreate}>
          <Plus size={16} />
          创建 Agent
        </button>
      </div>

      {loading ? (
        <div className={styles.loading}>加载中...</div>
      ) : (
        <div className={styles.grid}>
          {agents.map((agent) => {
            const color = AGENT_TYPE_COLORS[agent.type] || '#6b7280'
            return (
              <div key={agent.name} className={styles.card}>
                <div className={styles.cardHeader}>
                  <div className={styles.agentIcon} style={{ background: color }}>
                    {TypeIcon(agent.type)}
                  </div>
                  <div className={styles.agentInfo}>
                    <h3 className={styles.agentName}>{agent.name}</h3>
                    <span className={styles.agentType} style={{ color }}>
                      {agent.type}
                    </span>
                  </div>
                </div>
                <p className={styles.description}>{agent.description || '无描述'}</p>
                {agent.tools && agent.tools.length > 0 && (
                  <div className={styles.tools}>
                    {agent.tools.slice(0, 5).map((t) => (
                      <span key={t} className={styles.toolBadge}>{t}</span>
                    ))}
                    {agent.tools.length > 5 && <span className={styles.toolBadge}>+{agent.tools.length - 5}</span>}
                  </div>
                )}
                <div className={styles.actions}>
                  <button className={styles.actionBtn} onClick={() => handleEdit(agent)} title="编辑">
                    <Edit size={14} />
                  </button>
                  <button className={styles.actionBtn} title="复制">
                    <Copy size={14} />
                  </button>
                  <button className={`${styles.actionBtn} ${styles.danger}`} title="删除">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            )
          })}
          {agents.length === 0 && (
            <div className={styles.empty}>暂无 Agent，点击"创建 Agent"开始</div>
          )}
        </div>
      )}

      {showCreate && (
        <AgentCreateModal
          agent={editingAgent}
          onClose={handleClose}
        />
      )}
    </div>
  )
}

export default React.memo(AgentListPage)
