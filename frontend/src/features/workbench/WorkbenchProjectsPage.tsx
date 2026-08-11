import { useState, type FormEvent } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { shallow } from 'zustand/shallow'
import { getWorkbenchErrorMessage, workbenchApi } from './workbenchApi'
import { useWorkbenchProjectStore } from './store/workbenchProjectStore'
import type { WorkbenchProjectSummary } from './workbenchTypes'
import styles from './WorkbenchProjectsPage.module.css'

export default function WorkbenchProjectsPage() {
  const navigate = useNavigate()
  const {
    projects,
    currentProjectId,
    phase,
    error: storeError,
    activeScopeKey,
    hydrate,
    selectProject,
  } = useWorkbenchProjectStore((state) => ({
    projects: state.projects,
    currentProjectId: state.currentProjectId,
    phase: state.phase,
    error: state.error,
    activeScopeKey: state.activeScopeKey,
    hydrate: state.hydrate,
    selectProject: state.selectProject,
  }), shallow)

  const [showCreate, setShowCreate] = useState(false)
  const [displayName, setDisplayName] = useState('')
  const [root, setRoot] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyProjectId, setBusyProjectId] = useState<string | null>(null)

  const refresh = async () => {
    if (activeScopeKey) await hydrate(activeScopeKey, { force: true })
  }

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault()
    const name = displayName.trim()
    const candidateRoot = root.trim()
    if (!name || !candidateRoot) {
      setActionError('请输入项目名称和服务器绝对路径')
      return
    }
    try {
      setActionError(null)
      await workbenchApi.createProject({ displayName: name, root: candidateRoot })
      setShowCreate(false)
      setDisplayName('')
      setRoot('')
      await refresh()
    } catch (error) {
      setActionError(getWorkbenchErrorMessage(error))
    }
  }

  const runProjectAction = async (
    project: WorkbenchProjectSummary,
    action: () => Promise<unknown>,
  ) => {
    try {
      setBusyProjectId(project.id)
      setActionError(null)
      await action()
      await refresh()
    } catch (error) {
      setActionError(getWorkbenchErrorMessage(error))
    } finally {
      setBusyProjectId(null)
    }
  }

  const handleRename = async (project: WorkbenchProjectSummary) => {
    const nextName = window.prompt('请输入新的项目名称', project.displayName)?.trim()
    if (!nextName || nextName === project.displayName) return
    await runProjectAction(project, () => workbenchApi.updateProject(project.id, {
      displayName: nextName,
    }))
  }

  const handleDelete = async (project: WorkbenchProjectSummary) => {
    const confirmed = window.confirm(
      `只移除 Open-AwA 登记，不删除磁盘目录。确认删除“${project.displayName}”的登记吗？`,
    )
    if (!confirmed) return
    await runProjectAction(project, () => workbenchApi.deleteProject(project.id))
  }

  const openProject = async (
    project: WorkbenchProjectSummary,
    destination: '/workbench/editor' | '/workbench/agents',
  ) => {
    try {
      setBusyProjectId(project.id)
      setActionError(null)
      await selectProject(project.id)
      await navigate({ to: destination })
    } catch (error) {
      setActionError(getWorkbenchErrorMessage(error))
    } finally {
      setBusyProjectId(null)
    }
  }

  if (phase === 'loading' || phase === 'idle') {
    return <section className={styles.container} aria-busy="true">正在加载工作台项目...</section>
  }

  const visibleError = actionError ?? storeError

  return (
    <section className={styles.container} aria-labelledby="workbench-projects-title">
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>工作台</p>
          <h1 id="workbench-projects-title">工作台项目</h1>
          <p className={styles.intro}>登记服务器上的代码项目，并在编辑器与 Agents 之间共享同一项目上下文。</p>
        </div>
        <button type="button" className={styles.primaryButton} onClick={() => setShowCreate(true)}>
          登记项目
        </button>
      </header>

      {visibleError ? (
        <div className={styles.error} role="alert">
          <span>{visibleError}</span>
          <button type="button" onClick={() => setActionError(null)} aria-label="关闭错误提示">关闭</button>
        </div>
      ) : null}

      {showCreate ? (
        <form className={styles.form} onSubmit={handleCreate}>
          <h2>登记服务器项目</h2>
          <label>
            项目名称
            <input
              value={displayName}
              maxLength={200}
              onChange={(event) => setDisplayName(event.target.value)}
              autoComplete="off"
            />
          </label>
          <label>
            服务器绝对路径
            <input
              value={root}
              onChange={(event) => setRoot(event.target.value)}
              placeholder="D:\\work\\project"
              autoComplete="off"
            />
          </label>
          <p className={styles.formHint}>路径仅用于本次服务端登记，后续请求只使用项目 ID。</p>
          <div className={styles.formActions}>
            <button type="submit" className={styles.primaryButton}>确认登记</button>
            <button type="button" onClick={() => setShowCreate(false)}>取消</button>
          </div>
        </form>
      ) : null}

      {projects.length === 0 ? (
        <div className={styles.empty}>
          <h2>尚未登记项目</h2>
          <p>登记一个服务器允许范围内的代码目录后，即可进入编辑器或 Agents。</p>
          <button type="button" onClick={() => setShowCreate(true)}>登记第一个项目</button>
        </div>
      ) : (
        <div className={styles.grid}>
          {projects.map((project) => {
            const isCurrent = project.id === currentProjectId
            const busy = busyProjectId === project.id
            return (
              <article
                key={project.id}
                className={`${styles.card} ${isCurrent ? styles.currentCard : ''}`}
              >
                <div className={styles.cardTitleRow}>
                  <h2>{project.displayName}</h2>
                  <span className={project.isEnabled ? styles.enabled : styles.disabled}>
                    {project.isEnabled ? '已启用' : '已禁用'}
                  </span>
                  {isCurrent ? <span className={styles.current}>当前项目</span> : null}
                </div>
                <p className={styles.timestamp}>
                  最近打开：{project.lastOpenedAt ? new Date(project.lastOpenedAt).toLocaleString() : '尚未打开'}
                </p>
                <div className={styles.primaryActions}>
                  <button
                    type="button"
                    disabled={!project.isEnabled || busy}
                    aria-label={`在编辑器中打开 ${project.displayName}`}
                    onClick={() => void openProject(project, '/workbench/editor')}
                  >
                    打开编辑器
                  </button>
                  <button
                    type="button"
                    disabled={!project.isEnabled || busy}
                    aria-label={`在 Agents 中打开 ${project.displayName}`}
                    onClick={() => void openProject(project, '/workbench/agents')}
                  >
                    打开 Agents
                  </button>
                </div>
                <div className={styles.secondaryActions}>
                  <button
                    type="button"
                    disabled={busy}
                    aria-label={`重命名 ${project.displayName}`}
                    onClick={() => void handleRename(project)}
                  >
                    重命名
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    aria-label={`${project.isEnabled ? '禁用' : '启用'} ${project.displayName}`}
                    onClick={() => void runProjectAction(project, () => workbenchApi.updateProject(
                      project.id,
                      { isEnabled: !project.isEnabled },
                    ))}
                  >
                    {project.isEnabled ? '禁用' : '启用'}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    aria-label={`删除 ${project.displayName}`}
                    onClick={() => void handleDelete(project)}
                  >
                    删除登记
                  </button>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}
