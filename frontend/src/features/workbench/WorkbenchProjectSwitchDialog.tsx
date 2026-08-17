import { shallow } from 'zustand/shallow'
import { useWorkbenchProjectStore } from './store/workbenchProjectStore'
import styles from './WorkbenchShell.module.css'

function blockerMessage(kind: string): string {
  switch (kind) {
    case 'git-operation':
      return 'Git 写操作仍在进行，请等待完成后重试。'
    case 'running-command':
      return '项目仍有运行中的命令，请先停止命令。'
    case 'active-agent-turn':
      return 'Agent 回合仍在进行，请先取消或等待完成。'
    default:
      return '项目当前仍有未完成操作。'
  }
}

export default function WorkbenchProjectSwitchDialog() {
  const {
    pendingSwitch,
    phase,
    error,
    confirmSwitch,
    cancelSwitch,
  } = useWorkbenchProjectStore((state) => ({
    pendingSwitch: state.pendingSwitch,
    phase: state.phase,
    error: state.error,
    confirmSwitch: state.confirmSwitch,
    cancelSwitch: state.cancelSwitch,
  }), shallow)

  if (!pendingSwitch) return null

  const dirtyPaths = pendingSwitch.blockers.flatMap((blocker) => (
    blocker.kind === 'dirty-files' ? blocker.relativePaths : []
  ))
  const hardBlockers = pendingSwitch.blockers.filter((blocker) => blocker.kind !== 'dirty-files')
  const switching = phase === 'switching'

  return (
    <div className={styles.switchBackdrop}>
      <section
        className={styles.switchDialog}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="workbench-switch-title"
        aria-describedby="workbench-switch-description"
      >
        <h2 id="workbench-switch-title">切换工作台项目</h2>
        <p id="workbench-switch-description">
          当前项目存在尚未处理的状态。服务端项目上下文会在处理完成后才切换。
        </p>

        {dirtyPaths.length > 0 && (
          <div className={styles.switchBlocker}>
            <strong>未保存文件</strong>
            <ul className={styles.switchFileList}>
              {dirtyPaths.map((path) => <li key={path}>{path}</li>)}
            </ul>
          </div>
        )}

        {hardBlockers.map((blocker, index) => (
          <p className={styles.switchBlocker} key={`${blocker.kind}-${index}`}>
            {blockerMessage(blocker.kind)}
          </p>
        ))}

        {error && <p className={styles.switchError} role="alert">{error}</p>}

        <div className={styles.switchActions}>
          {hardBlockers.length === 0 && dirtyPaths.length > 0 && (
            <>
              <button
                type="button"
                disabled={switching}
                onClick={() => void confirmSwitch('save').catch(() => undefined)}
              >
                保存并切换
              </button>
              <button
                type="button"
                disabled={switching}
                onClick={() => void confirmSwitch('discard').catch(() => undefined)}
              >
                放弃并切换
              </button>
            </>
          )}
          <button type="button" disabled={switching} onClick={cancelSwitch}>
            取消
          </button>
        </div>
      </section>
    </div>
  )
}
