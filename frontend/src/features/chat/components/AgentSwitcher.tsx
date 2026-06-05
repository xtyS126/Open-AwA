/**
 * Agent 切换器 — 在聊天页面中切换当前 Agent 类型。
 * 改变 Agent 类型会影响系统提示、工具可用性和对话行为。
 */
import React, { useState, useEffect, useCallback } from 'react'
import { Eye, Zap, Wrench } from 'lucide-react'
import { subagentsApi, AgentType } from '@/shared/api/subagentsApi'
import styles from './AgentSwitcher.module.css'

interface AgentSwitcherProps {
  currentAgent: string
  onAgentChange: (agentType: string) => void
}

const AGENT_ICONS: Record<string, React.FC<{ size?: number }>> = {
  Explore: Eye,
  Plan: Zap,
  'general-purpose': Wrench,
}

const AGENT_LABELS: Record<string, string> = {
  Explore: '探索',
  Plan: '规划',
  'general-purpose': '通用',
}

const DEFAULT_AGENTS: AgentType[] = [
  { name: 'Explore', type: 'Explore', description: '只读代码搜索和调研', isolation_mode: 'inherit' },
  { name: 'Plan', type: 'Plan', description: '仅只读规划分析', isolation_mode: 'inherit' },
  { name: 'general-purpose', type: 'general-purpose', description: '完整读写能力', isolation_mode: 'fresh' },
]

const AgentSwitcher: React.FC<AgentSwitcherProps> = ({ currentAgent, onAgentChange }) => {
  const [agents, setAgents] = useState<AgentType[]>(DEFAULT_AGENTS)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let cancelled = false
    subagentsApi.listAgents().then((data) => {
      if (!cancelled && data.agents?.length > 0) {
        setAgents(data.agents)
      }
    }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  const selectedAgent = agents.find((a) => a.type === currentAgent) || agents[0]
  const Icon = AGENT_ICONS[currentAgent] || Zap

  return (
    <div className={styles.switcher}>
      <button className={styles.trigger} onClick={() => setOpen(!open)} title="切换 Agent 类型">
        <Icon size={14} />
        <span className={styles.label}>{AGENT_LABELS[currentAgent] || currentAgent}</span>
        <span className={styles.arrow}>▾</span>
      </button>

      {open && (
        <>
          <div className={styles.backdrop} onClick={() => setOpen(false)} />
          <div className={styles.dropdown}>
            {agents.map((agent) => {
              const AgentIcon = AGENT_ICONS[agent.type] || Zap
              return (
                <div
                  key={agent.type}
                  className={`${styles.item} ${agent.type === currentAgent ? styles.active : ''}`}
                  onClick={() => { onAgentChange(agent.type); setOpen(false) }}
                >
                  <div className={styles.itemIcon}>
                    <AgentIcon size={16} />
                  </div>
                  <div className={styles.itemInfo}>
                    <span className={styles.itemName}>{agent.name}</span>
                    <span className={styles.itemDesc}>{agent.description}</span>
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

export default React.memo(AgentSwitcher)
