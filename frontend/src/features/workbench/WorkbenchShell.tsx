import { Outlet } from '@/shared/routing'
import WorkbenchContextProvider from './WorkbenchContextProvider'
import WorkbenchProjectBar from './WorkbenchProjectBar'
import WorkbenchProjectSwitchDialog from './WorkbenchProjectSwitchDialog'
import WorkbenchRuntimeDock from './WorkbenchRuntimeDock'
import styles from './WorkbenchShell.module.css'

export default function WorkbenchShell() {
  return (
    <WorkbenchContextProvider>
      <section className={styles.shell} data-testid="workbench-shell">
        <WorkbenchProjectBar />
        <WorkbenchProjectSwitchDialog />
        <div className={styles.content}>
          <Outlet />
        </div>
        <WorkbenchRuntimeDock />
      </section>
    </WorkbenchContextProvider>
  )
}
