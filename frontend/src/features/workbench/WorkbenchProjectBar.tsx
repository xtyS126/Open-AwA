import { shallow } from 'zustand/shallow'
import { Link } from '@/shared/routing'
import {
  selectCurrentWorkbenchProject,
  useWorkbenchProjectStore,
} from './store/workbenchProjectStore'
import { asWorkbenchProjectId } from './workbenchTypes'
import styles from './WorkbenchShell.module.css'

export default function WorkbenchProjectBar() {
  const {
    projects,
    currentProjectId,
    currentProject,
    phase,
    error,
    selectProject,
  } = useWorkbenchProjectStore((state) => ({
    projects: state.projects,
    currentProjectId: state.currentProjectId,
    currentProject: selectCurrentWorkbenchProject(state),
    phase: state.phase,
    error: state.error,
    selectProject: state.selectProject,
  }), shallow)

  const handleProjectChange = (value: string) => {
    if (!value || value === currentProjectId) return
    void selectProject(asWorkbenchProjectId(value)).catch(() => undefined)
  }

  return (
    <section className={styles.projectBar} aria-label="当前工作台项目">
      <div className={styles.projectIdentity}>
        <span className={styles.eyebrow}>当前项目</span>
        <strong className={styles.projectName}>
          {currentProject?.displayName ?? '尚未选择项目'}
        </strong>
      </div>

      <label className={styles.selectorLabel}>
        <span className={styles.visuallyHidden}>切换工作台项目</span>
        <select
          className={styles.selector}
          value={currentProjectId ?? ''}
          disabled={phase === 'loading' || phase === 'switching' || projects.length === 0}
          onChange={(event) => handleProjectChange(event.target.value)}
        >
          <option value="">选择项目</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id} disabled={!project.isEnabled}>
              {project.displayName}{project.isEnabled ? '' : '（已禁用）'}
            </option>
          ))}
        </select>
      </label>

      <Link className={styles.manageLink} to="/workbench/projects">
        管理项目
      </Link>

      {phase === 'switching' && <span className={styles.status}>正在切换</span>}
      {error && <span className={styles.error} role="alert">{error}</span>}
    </section>
  )
}

