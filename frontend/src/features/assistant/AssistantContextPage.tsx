import { useEffect, useState } from 'react'
import { BookOpen, FolderKanban, Save, UserRound, Volume2 } from 'lucide-react'
import { useSessionStore } from '@/features/chat/store/sessionStore'
import { ttsApi } from '@/features/tts/ttsApi'
import { workspaceApi } from '@/features/workspace/workspaceApi'
import { conversationAPI } from '@/shared/api/conversationApi'
import { memoryAPI } from '@/shared/api/memoryApi'
import * as rolesApi from '@/shared/api/rolesApi'
import type { LongTermMemoryItem } from '@/shared/api/types'
import type { AgentRole } from '@/shared/types/role'
import type { SpeakerInfo } from '@/features/tts/ttsApi'
import type { WorkspaceItem } from '@/features/workspace/workspaceApi'
import styles from './AssistantContextPage.module.css'

const MAX_SELECTED_MEMORIES = 20

function formatLoadError(section: string, error: unknown): string {
  const detail = error instanceof Error && error.message.trim() ? `：${error.message}` : ''
  return `${section}加载失败${detail}`
}

function formatSaveError(error: unknown): string {
  const detail = error instanceof Error && error.message.trim() ? `：${error.message}` : ''
  return `保存上下文失败${detail}`
}

export default function AssistantContextPage() {
  const sessionId = useSessionStore((state) => state.sessionId)
  const hasActiveSession = Boolean(sessionId && sessionId !== 'default')

  const [roleId, setRoleId] = useState<string | null>(null)
  const [workspaceId, setWorkspaceId] = useState('default')
  const [selectedMemoryIds, setSelectedMemoryIds] = useState<number[]>([])
  const [speakerId, setSpeakerId] = useState<string | null>(null)

  const [roles, setRoles] = useState<AgentRole[]>([])
  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([])
  const [memories, setMemories] = useState<LongTermMemoryItem[]>([])
  const [speakers, setSpeakers] = useState<SpeakerInfo[]>([])

  const [contextLoading, setContextLoading] = useState(false)
  const [rolesLoading, setRolesLoading] = useState(false)
  const [workspacesLoading, setWorkspacesLoading] = useState(false)
  const [memoriesLoading, setMemoriesLoading] = useState(false)
  const [speakersLoading, setSpeakersLoading] = useState(false)

  const [contextError, setContextError] = useState<string | null>(null)
  const [rolesError, setRolesError] = useState<string | null>(null)
  const [workspacesError, setWorkspacesError] = useState<string | null>(null)
  const [memoriesError, setMemoriesError] = useState<string | null>(null)
  const [speakersError, setSpeakersError] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!hasActiveSession) {
      return
    }

    let cancelled = false

    setRoleId(null)
    setWorkspaceId('default')
    setSelectedMemoryIds([])
    setSpeakerId(null)
    setContextError(null)
    setRolesError(null)
    setWorkspacesError(null)
    setMemoriesError(null)
    setSpeakersError(null)
    setSaveError(null)
    setSaveMessage(null)

    setContextLoading(true)
    void conversationAPI.getAssistantContext(sessionId)
      .then(({ data }) => {
        if (cancelled) return
        setRoleId(data.role_id)
        setWorkspaceId(data.workspace_id || 'default')
        setSelectedMemoryIds(data.selected_memory_ids.slice(0, MAX_SELECTED_MEMORIES))
        setSpeakerId(data.speaker_id)
      })
      .catch((error: unknown) => {
        if (!cancelled) setContextError(formatLoadError('会话上下文', error))
      })
      .finally(() => {
        if (!cancelled) setContextLoading(false)
      })

    setRolesLoading(true)
    void rolesApi.getRoles()
      .then((items) => {
        if (!cancelled) setRoles(items)
      })
      .catch((error: unknown) => {
        if (!cancelled) setRolesError(formatLoadError('角色', error))
      })
      .finally(() => {
        if (!cancelled) setRolesLoading(false)
      })

    setWorkspacesLoading(true)
    void workspaceApi.list(true)
      .then(({ workspaces: items }) => {
        if (!cancelled) setWorkspaces(items)
      })
      .catch((error: unknown) => {
        if (!cancelled) setWorkspacesError(formatLoadError('项目', error))
      })
      .finally(() => {
        if (!cancelled) setWorkspacesLoading(false)
      })

    setMemoriesLoading(true)
    void memoryAPI.getLongTerm()
      .then(({ data }) => {
        if (!cancelled) setMemories(data)
      })
      .catch((error: unknown) => {
        if (!cancelled) setMemoriesError(formatLoadError('知识', error))
      })
      .finally(() => {
        if (!cancelled) setMemoriesLoading(false)
      })

    setSpeakersLoading(true)
    void ttsApi.listSpeakers()
      .then(({ speakers: items }) => {
        if (!cancelled) setSpeakers(items)
      })
      .catch((error: unknown) => {
        if (!cancelled) setSpeakersError(formatLoadError('声音', error))
      })
      .finally(() => {
        if (!cancelled) setSpeakersLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [hasActiveSession, sessionId])

  const toggleMemory = (memoryId: number, checked: boolean) => {
    setSaveError(null)
    setSaveMessage(null)
    setSelectedMemoryIds((current) => {
      if (!checked) {
        return current.filter((id) => id !== memoryId)
      }
      if (current.includes(memoryId) || current.length >= MAX_SELECTED_MEMORIES) {
        return current
      }
      return [...current, memoryId]
    })
  }

  const saveContext = async () => {
    if (!hasActiveSession) return
    setSaving(true)
    setSaveError(null)
    setSaveMessage(null)
    try {
      const { data } = await conversationAPI.updateAssistantContext(sessionId, {
        role_id: roleId,
        workspace_id: workspaceId,
        selected_memory_ids: selectedMemoryIds,
        speaker_id: speakerId,
      })
      setRoleId(data.role_id)
      setWorkspaceId(data.workspace_id)
      setSelectedMemoryIds(data.selected_memory_ids.slice(0, MAX_SELECTED_MEMORIES))
      setSpeakerId(data.speaker_id)
      setSaveMessage('上下文已保存')
    } catch (error) {
      setSaveError(formatSaveError(error))
    } finally {
      setSaving(false)
    }
  }

  if (!hasActiveSession) {
    return (
      <div className={styles.page}>
        <section className={styles.emptyState} aria-labelledby="assistant-context-empty-title">
          <span className={styles.emptyIcon} aria-hidden="true">
            <BookOpen size={28} />
          </span>
          <h1 id="assistant-context-empty-title">请先选择或创建一个会话</h1>
          <p>助手上下文按会话保存。进入一个会话后，即可配置角色、项目、知识和声音。</p>
        </section>
      </div>
    )
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div>
          <span className={styles.eyebrow}>当前会话</span>
          <h1>助手上下文</h1>
          <p>为这次对话选择角色、项目和显式知识；声音作为本会话的朗读偏好保存。</p>
        </div>
        <code className={styles.sessionId}>{sessionId}</code>
      </header>

      {contextError && <div className={styles.pageAlert} role="alert">{contextError}</div>}

      <div className={styles.sections}>
        <fieldset className={styles.section} aria-label="角色上下文">
          <legend>
            <span className={styles.sectionIcon} aria-hidden="true"><UserRound size={20} /></span>
            <span><strong>角色上下文</strong><small>决定助手的身份、语气和可用能力</small></span>
          </legend>
          {rolesLoading ? <p className={styles.status}>正在加载角色…</p> : null}
          {rolesError ? <p className={styles.error} role="alert">{rolesError}</p> : null}
          {!rolesLoading && !rolesError ? (
            <div className={styles.optionList}>
              <label className={styles.option}>
                <input type="radio" name="assistant-role" checked={roleId === null} onChange={() => setRoleId(null)} />
                <span><strong>不使用角色</strong><small>沿用助手默认行为</small></span>
              </label>
              {roles.map((role) => (
                <label className={styles.option} key={role.id}>
                  <input type="radio" name="assistant-role" checked={roleId === role.id} onChange={() => setRoleId(role.id)} />
                  <span><strong>{role.name}</strong>{role.description ? <small>{role.description}</small> : null}</span>
                </label>
              ))}
              {roles.length === 0 ? <p className={styles.muted}>暂无可用角色</p> : null}
            </div>
          ) : null}
        </fieldset>

        <fieldset className={styles.section} aria-label="项目上下文">
          <legend>
            <span className={styles.sectionIcon} aria-hidden="true"><FolderKanban size={20} /></span>
            <span><strong>项目上下文</strong><small>限定工作区资源和记忆范围</small></span>
          </legend>
          {workspacesLoading ? <p className={styles.status}>正在加载项目…</p> : null}
          {workspacesError ? <p className={styles.error} role="alert">{workspacesError}</p> : null}
          {!workspacesLoading && !workspacesError ? (
            <div className={styles.optionList}>
              {workspaces.map((workspace) => (
                <label className={styles.option} key={workspace.id}>
                  <input type="radio" name="assistant-workspace" checked={workspaceId === workspace.id} onChange={() => setWorkspaceId(workspace.id)} />
                  <span><strong>{workspace.name}</strong>{workspace.description ? <small>{workspace.description}</small> : null}</span>
                </label>
              ))}
              {workspaces.length === 0 ? <p className={styles.muted}>暂无可用项目</p> : null}
            </div>
          ) : null}
        </fieldset>

        <fieldset className={styles.section} aria-label="知识上下文">
          <legend>
            <span className={styles.sectionIcon} aria-hidden="true"><BookOpen size={20} /></span>
            <span><strong>知识上下文</strong><small>显式加入本次对话需要参考的长期记忆</small></span>
          </legend>
          <div className={styles.selectionCount} aria-live="polite">已选择 {selectedMemoryIds.length} / {MAX_SELECTED_MEMORIES}</div>
          {memoriesLoading ? <p className={styles.status}>正在加载知识…</p> : null}
          {memoriesError ? <p className={styles.error} role="alert">{memoriesError}</p> : null}
          {!memoriesLoading && !memoriesError ? (
            <div className={styles.optionList}>
              {memories.map((memory) => {
                const selected = selectedMemoryIds.includes(memory.id)
                const disabled = !selected && selectedMemoryIds.length >= MAX_SELECTED_MEMORIES
                return (
                  <label className={`${styles.option} ${disabled ? styles.disabledOption : ''}`} key={memory.id}>
                    <input
                      type="checkbox"
                      checked={selected}
                      disabled={disabled}
                      onChange={(event) => toggleMemory(memory.id, event.currentTarget.checked)}
                    />
                    <span><strong>{memory.content}</strong></span>
                  </label>
                )
              })}
              {memories.length === 0 ? <p className={styles.muted}>暂无可选知识</p> : null}
            </div>
          ) : null}
        </fieldset>

        <fieldset className={styles.section} aria-label="声音偏好">
          <legend>
            <span className={styles.sectionIcon} aria-hidden="true"><Volume2 size={20} /></span>
            <span><strong>声音偏好</strong><small>选择本会话朗读回复时使用的声音</small></span>
          </legend>
          {speakersLoading ? <p className={styles.status}>正在加载声音…</p> : null}
          {speakersError ? <p className={styles.error} role="alert">{speakersError}</p> : null}
          {!speakersLoading && !speakersError ? (
            <div className={styles.optionList}>
              <label className={styles.option}>
                <input type="radio" name="assistant-speaker" checked={speakerId === null} onChange={() => setSpeakerId(null)} />
                <span><strong>使用默认声音</strong><small>不为当前会话指定声音</small></span>
              </label>
              {speakers.map((speaker) => (
                <label className={styles.option} key={speaker.speaker_id}>
                  <input type="radio" name="assistant-speaker" checked={speakerId === speaker.speaker_id} onChange={() => setSpeakerId(speaker.speaker_id)} />
                  <span><strong>{speaker.name}</strong><small>{speaker.is_cloned ? '克隆声音' : speaker.language}</small></span>
                </label>
              ))}
              {speakers.length === 0 ? <p className={styles.muted}>暂无可用声音</p> : null}
            </div>
          ) : null}
        </fieldset>
      </div>

      <footer className={styles.actions}>
        <div className={styles.feedback} aria-live="polite">
          {saveError ? <span className={styles.error} role="alert">{saveError}</span> : null}
          {saveMessage ? <span className={styles.success}>{saveMessage}</span> : null}
        </div>
        <button
          type="button"
          className={styles.saveButton}
          disabled={saving || contextLoading}
          onClick={() => void saveContext()}
        >
          <Save size={18} aria-hidden="true" />
          {saving ? '正在保存…' : '保存上下文'}
        </button>
      </footer>
    </div>
  )
}
