import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import FilePreviewPane from '@/features/vibe-coding/components/FilePreviewPane'
import { appLogger } from '@/shared/utils/logger'
import { useWorkbenchProjectStore } from './store/workbenchProjectStore'
import { useWorkbenchRuntimeStore } from './store/workbenchRuntimeStore'
import { workbenchPreviewApi } from './workbenchPreviewApi'
import styles from './WorkbenchRuntimeDock.module.css'

const TerminalPane = lazy(() => import('@/features/vibe-coding/components/TerminalPane'))
const PREVIEW_RENEW_INTERVAL_MS = 10 * 60 * 1000

export default function WorkbenchRuntimeDock() {
  const currentProjectId = useWorkbenchProjectStore((state) => state.currentProjectId)
  const phase = useWorkbenchProjectStore((state) => state.phase)
  const switchGeneration = useWorkbenchProjectStore((state) => state.switchGeneration)
  const runtime = useWorkbenchRuntimeStore((state) => (
    currentProjectId ? state.projects[currentProjectId] : undefined
  ))
  const activateProject = useWorkbenchRuntimeStore((state) => state.activateProject)
  const setDockState = useWorkbenchRuntimeStore((state) => state.setDockState)
  const setTerminalBinding = useWorkbenchRuntimeStore((state) => state.setTerminalBinding)
  const setPreviewIntent = useWorkbenchRuntimeStore((state) => state.setPreviewIntent)
  const [portInput, setPortInput] = useState('5173')
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [creatingPreview, setCreatingPreview] = useState(false)
  const requestSerialRef = useRef(0)

  const readyProjectId = phase === 'ready' ? currentProjectId : null
  const activeRuntime = readyProjectId && runtime?.generation === switchGeneration
    ? runtime
    : undefined

  useEffect(() => {
    requestSerialRef.current += 1
    setCreatingPreview(false)
    setPreviewError(null)
    setPortInput('5173')
    if (readyProjectId) activateProject(readyProjectId, switchGeneration)
  }, [activateProject, readyProjectId, switchGeneration])

  const handleBindingChange = useCallback((sessionId: string | null) => {
    if (!readyProjectId) return
    setTerminalBinding(
      readyProjectId,
      switchGeneration,
      sessionId ? { kind: 'attached', sessionId } : { kind: 'none' },
    )
  }, [readyProjectId, setTerminalBinding, switchGeneration])

  useEffect(() => {
    if (!readyProjectId || activeRuntime?.previewIntent.kind !== 'web') return
    const previewId = activeRuntime.previewIntent.previewId
    const projectId = readyProjectId
    const generation = switchGeneration
    const timer = window.setInterval(() => {
      void workbenchPreviewApi.renew(projectId, previewId).catch((renewError: unknown) => {
        appLogger.warning({
          event: 'workbench_preview_renew_failed',
          module: 'workbench',
          action: 'preview',
          status: 'warning',
          message: '工作台 HTTP 预览租约续租失败',
          extra: {
            project_id: projectId,
            preview_id: previewId,
            error: renewError instanceof Error ? renewError.message : String(renewError),
          },
        })
      })
    }, PREVIEW_RENEW_INTERVAL_MS)

    return () => {
      window.clearInterval(timer)
      void workbenchPreviewApi.revoke(projectId, previewId).catch((revokeError: unknown) => {
        appLogger.warning({
          event: 'workbench_preview_revoke_failed',
          module: 'workbench',
          action: 'preview',
          status: 'warning',
          message: '工作台 HTTP 预览租约撤销失败',
          extra: {
            project_id: projectId,
            preview_id: previewId,
            error: revokeError instanceof Error ? revokeError.message : String(revokeError),
          },
        })
      })
      const latestRuntime = useWorkbenchRuntimeStore.getState().projects[projectId]
      if (
        latestRuntime?.generation === generation
        && latestRuntime.previewIntent.kind === 'web'
        && latestRuntime.previewIntent.previewId === previewId
      ) {
        setPreviewIntent(projectId, generation, { kind: 'none' })
      }
    }
  }, [activeRuntime?.previewIntent, readyProjectId, setPreviewIntent, switchGeneration])

  const handleCreatePreview = async (): Promise<void> => {
    if (!readyProjectId || !activeRuntime) return
    if (activeRuntime.terminalBinding.kind !== 'attached') {
      setPreviewError('终端尚未就绪，无法签发 HTTP 预览租约')
      return
    }
    const port = Number(portInput)
    if (!Number.isInteger(port) || port < 1024 || port > 65535) {
      setPreviewError('端口必须是 1024 到 65535 之间的整数')
      return
    }

    const projectId = readyProjectId
    const generation = switchGeneration
    const sessionId = activeRuntime.terminalBinding.sessionId
    const requestSerial = requestSerialRef.current + 1
    requestSerialRef.current = requestSerial
    setCreatingPreview(true)
    setPreviewError(null)
    try {
      const lease = await workbenchPreviewApi.create(projectId, {
        sessionKind: 'terminal',
        sessionId,
        port,
      })
      const latestProject = useWorkbenchProjectStore.getState()
      const latestRuntime = useWorkbenchRuntimeStore.getState().projects[projectId]
      const stale = requestSerialRef.current !== requestSerial
        || latestProject.phase !== 'ready'
        || latestProject.currentProjectId !== projectId
        || latestProject.switchGeneration !== generation
        || latestRuntime?.generation !== generation
      if (stale) {
        await workbenchPreviewApi.revoke(projectId, lease.previewId).catch(() => undefined)
        return
      }
      setPreviewIntent(projectId, generation, { kind: 'web', previewId: lease.previewId })
    } catch (createError) {
      if (requestSerialRef.current === requestSerial) {
        setPreviewError(createError instanceof Error ? createError.message : String(createError))
      }
    } finally {
      if (requestSerialRef.current === requestSerial) setCreatingPreview(false)
    }
  }

  const handleCloseDock = (): void => {
    if (!readyProjectId || !activeRuntime) return
    requestSerialRef.current += 1
    if (activeRuntime.previewIntent.kind === 'web') {
      setPreviewIntent(readyProjectId, switchGeneration, { kind: 'none' })
    }
    setDockState(readyProjectId, switchGeneration, { open: false })
  }

  if (!readyProjectId) {
    return (
      <aside className={styles.gate} data-testid="workbench-runtime-dock">
        选择可用项目后可启动终端和 HTTP 预览
      </aside>
    )
  }

  if (!activeRuntime) {
    return (
      <aside className={styles.gate} data-testid="workbench-runtime-dock">
        正在准备项目运行时
      </aside>
    )
  }

  if (!activeRuntime.dockOpen) {
    return (
      <aside className={styles.collapsed} data-testid="workbench-runtime-dock">
        <span>项目运行时</span>
        <button
          type="button"
          onClick={() => setDockState(readyProjectId, switchGeneration, { open: true })}
        >
          打开运行时面板
        </button>
      </aside>
    )
  }

  return (
    <aside className={styles.dock} data-testid="workbench-runtime-dock">
      <header className={styles.header}>
        <div className={styles.tabs} role="tablist" aria-label="工作台运行时">
          <button
            type="button"
            role="tab"
            aria-selected={activeRuntime.dockPanel === 'terminal'}
            onClick={() => setDockState(readyProjectId, switchGeneration, { panel: 'terminal' })}
          >
            终端
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeRuntime.dockPanel === 'preview'}
            onClick={() => setDockState(readyProjectId, switchGeneration, { panel: 'preview' })}
          >
            预览
          </button>
        </div>
        <span className={styles.protocol}>仅支持 HTTP 预览</span>
        <button type="button" onClick={handleCloseDock}>关闭运行时面板</button>
      </header>

      <div className={styles.body}>
        <section
          className={activeRuntime.dockPanel === 'terminal' ? styles.panel : styles.hiddenPanel}
          aria-hidden={activeRuntime.dockPanel !== 'terminal'}
        >
          <Suspense fallback={<div className={styles.gate}>正在加载终端</div>}>
            <TerminalPane
              key={`${readyProjectId}:${switchGeneration}`}
              projectId={readyProjectId}
              generation={switchGeneration}
              onBindingChange={handleBindingChange}
            />
          </Suspense>
        </section>

        <section
          className={activeRuntime.dockPanel === 'preview' ? styles.previewPanel : styles.hiddenPanel}
          aria-hidden={activeRuntime.dockPanel !== 'preview'}
        >
          <div className={styles.previewControls}>
            <label>
              <span>HTTP 预览端口</span>
              <input
                type="number"
                min={1024}
                max={65535}
                value={portInput}
                onChange={(event) => setPortInput(event.target.value)}
              />
            </label>
            <button
              type="button"
              onClick={() => void handleCreatePreview()}
              disabled={creatingPreview || activeRuntime.terminalBinding.kind !== 'attached'}
            >
              {creatingPreview ? '正在创建' : '创建 HTTP 预览'}
            </button>
            {previewError && <span className={styles.error}>{previewError}</span>}
          </div>
          <FilePreviewPane
            key={`${readyProjectId}:${switchGeneration}`}
            projectId={readyProjectId}
            intent={activeRuntime.previewIntent}
          />
        </section>
      </div>
    </aside>
  )
}
