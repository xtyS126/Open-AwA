/**
 * 角色管理页面 — 展示预设角色和自定义角色，支持创建、编辑、删除。
 */
import React, { useState, useEffect, useCallback } from 'react'
import { Plus, Trash2, Edit3, Star, Users } from 'lucide-react'
import { getRoles, createRole, updateRole, deleteRole } from '@/shared/api/rolesApi'
import type { AgentRole, RoleCreateRequest, RolePersonality } from '@/shared/types/role'
import styles from './RolesPage.module.css'

/** 角色编辑器模态框 */
function RoleEditorModal({
  role,
  onSave,
  onClose,
}: {
  role: AgentRole | null
  onSave: (data: RoleCreateRequest) => void
  onClose: () => void
}) {
  const [name, setName] = useState(role?.name || '')
  const [description, setDescription] = useState(role?.description || '')
  const [systemPrompt, setSystemPrompt] = useState(role?.system_prompt || '')
  const [creativity, setCreativity] = useState(role?.personality?.creativity ?? 0.5)
  const [formality, setFormality] = useState(role?.personality?.formality ?? 0.5)
  const [tone, setTone] = useState<RolePersonality['tone']>(role?.personality?.tone || 'professional')
  const [verbosity, setVerbosity] = useState<RolePersonality['verbosity']>(role?.personality?.verbosity || 'normal')
  const [temperature, setTemperature] = useState(role?.model_config?.temperature ?? 0.7)
  const [maxTokens, setMaxTokens] = useState(role?.model_config?.max_tokens ?? 4096)

  const handleSubmit = () => {
    if (!name.trim() || !systemPrompt.trim()) return
    onSave({
      name,
      description,
      system_prompt: systemPrompt,
      personality: { tone, verbosity, creativity, formality },
      model_config_override: { temperature, max_tokens: maxTokens },
    })
  }

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <h2>{role ? '编辑角色' : '创建角色'}</h2>

        <div className={styles.formGroup}>
          <label>角色名称 *</label>
          <input type="text" value={name} onChange={e => setName(e.target.value)} placeholder="输入角色名称" />
        </div>

        <div className={styles.formGroup}>
          <label>角色描述</label>
          <input type="text" value={description} onChange={e => setDescription(e.target.value)} placeholder="简要描述角色用途" />
        </div>

        <div className={styles.formGroup}>
          <label>系统提示词 *</label>
          <textarea
            value={systemPrompt}
            onChange={e => setSystemPrompt(e.target.value)}
            rows={6}
            placeholder="定义角色的行为和回复风格"
          />
        </div>

        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>语气</label>
            <select value={tone} onChange={e => setTone(e.target.value as RolePersonality['tone'])}>
              <option value="professional">专业</option>
              <option value="casual">随意</option>
              <option value="friendly">友好</option>
              <option value="strict">严格</option>
            </select>
          </div>
          <div className={styles.formGroup}>
            <label>详细度</label>
            <select value={verbosity} onChange={e => setVerbosity(e.target.value as RolePersonality['verbosity'])}>
              <option value="concise">简洁</option>
              <option value="normal">适中</option>
              <option value="detailed">详细</option>
            </select>
          </div>
        </div>

        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>创造力: {creativity.toFixed(1)}</label>
            <input type="range" min="0" max="1" step="0.1" value={creativity} onChange={e => setCreativity(Number(e.target.value))} />
          </div>
          <div className={styles.formGroup}>
            <label>正式度: {formality.toFixed(1)}</label>
            <input type="range" min="0" max="1" step="0.1" value={formality} onChange={e => setFormality(Number(e.target.value))} />
          </div>
        </div>

        <div className={styles.formRow}>
          <div className={styles.formGroup}>
            <label>温度: {temperature.toFixed(1)}</label>
            <input type="range" min="0" max="1" step="0.1" value={temperature} onChange={e => setTemperature(Number(e.target.value))} />
          </div>
          <div className={styles.formGroup}>
            <label>最大 Token</label>
            <input type="number" value={maxTokens} onChange={e => setMaxTokens(Number(e.target.value))} min={256} max={32768} step={256} />
          </div>
        </div>

        <div className={styles.modalActions}>
          <button className={styles.cancelBtn} onClick={onClose}>取消</button>
          <button className={styles.saveBtn} onClick={handleSubmit} disabled={!name.trim() || !systemPrompt.trim()}>
            {role ? '保存' : '创建'}
          </button>
        </div>
      </div>
    </div>
  )
}

/** 角色管理页面主组件 */
function RolesPage() {
  const [roles, setRoles] = useState<AgentRole[]>([])
  const [loading, setLoading] = useState(true)
  const [editingRole, setEditingRole] = useState<AgentRole | null>(null)
  const [showEditor, setShowEditor] = useState(false)

  // 加载角色列表
  const loadRoles = useCallback(async () => {
    try {
      setLoading(true)
      const roleList = await getRoles()
      setRoles(roleList)
    } catch {
      // 加载失败时保持空列表
      setRoles([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadRoles() }, [loadRoles])

  // 创建角色
  const handleCreate = () => {
    setEditingRole(null)
    setShowEditor(true)
  }

  // 编辑角色
  const handleEdit = (role: AgentRole) => {
    setEditingRole(role)
    setShowEditor(true)
  }

  // 删除角色
  const handleDelete = async (roleId: string) => {
    if (!confirm('确定要删除此角色吗？')) return
    try {
      await deleteRole(roleId)
      loadRoles()
    } catch {
      // 删除失败时静默处理，保留当前列表
    }
  }

  // 保存角色（创建或更新）
  const handleSave = async (data: RoleCreateRequest) => {
    try {
      if (editingRole) {
        await updateRole(editingRole.id, data)
      } else {
        await createRole(data)
      }
      setShowEditor(false)
      loadRoles()
    } catch {
      // 保存失败时静默处理，保留编辑器
    }
  }

  const customRoles = roles.filter(r => !r.is_preset)
  const presetRoles = roles.filter(r => r.is_preset)

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>角色管理</h1>
        <button className={styles.createBtn} onClick={handleCreate}>
          <Plus size={18} />
          创建角色
        </button>
      </div>

      {loading ? (
        <div className={styles.loading}>加载中...</div>
      ) : (
        <>
          {/* 预设角色 */}
          {presetRoles.length > 0 && (
            <section className={styles.section}>
              <h2 className={styles.sectionTitle}>
                <Star size={18} />
                预设角色
              </h2>
              <div className={styles.grid}>
                {presetRoles.map(role => (
                  <div key={role.id} className={styles.card}>
                    <div className={styles.cardHeader}>
                      <h3>{role.name}</h3>
                      <span className={styles.presetBadge}>预设</span>
                    </div>
                    <p className={styles.cardDesc}>{role.description}</p>
                    <div className={styles.cardMeta}>
                      <span>使用 {role.usage_count} 次</span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 自定义角色 */}
          <section className={styles.section}>
            <h2 className={styles.sectionTitle}>
              <Users size={18} />
              自定义角色
            </h2>
            {customRoles.length === 0 ? (
              <p className={styles.empty}>暂无自定义角色，点击上方按钮创建</p>
            ) : (
              <div className={styles.grid}>
                {customRoles.map(role => (
                  <div key={role.id} className={styles.card}>
                    <div className={styles.cardHeader}>
                      <h3>{role.name}</h3>
                      <div className={styles.cardActions}>
                        <button onClick={() => handleEdit(role)} title="编辑">
                          <Edit3 size={16} />
                        </button>
                        <button onClick={() => handleDelete(role.id)} title="删除">
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </div>
                    <p className={styles.cardDesc}>{role.description}</p>
                    <div className={styles.cardMeta}>
                      <span>使用 {role.usage_count} 次</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {/* 角色编辑器模态框 */}
      {showEditor && (
        <RoleEditorModal
          role={editingRole}
          onSave={handleSave}
          onClose={() => setShowEditor(false)}
        />
      )}
    </div>
  )
}

export default React.memo(RolesPage)
