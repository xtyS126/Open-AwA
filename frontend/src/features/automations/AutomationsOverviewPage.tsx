import { Activity, CalendarClock, Network, Workflow } from 'lucide-react'
import { Link } from '@/shared/routing'
import PageLayout from '@/shared/components/PageLayout/PageLayout'
import styles from './AutomationsOverviewPage.module.css'

const lifecycleEntries = [
  {
    path: '/automations/flows',
    label: '流程',
    description: '设计触发器、条件分支与可复用执行步骤。',
    icon: Workflow,
  },
  {
    path: '/automations/schedules',
    label: '计划',
    description: '管理定时触发、AI 任务与插件任务。',
    icon: CalendarClock,
  },
  {
    path: '/automations/executors',
    label: '执行者',
    description: '配置子智能体模板、资源限制与可用状态。',
    icon: Network,
  },
  {
    path: '/automations/runs',
    label: '运行',
    description: '查看执行记录、日志、产物、审批与协作。',
    icon: Activity,
  },
] as const

export default function AutomationsOverviewPage() {
  return (
    <PageLayout title="自动化概览">
      <section className={styles['hero']} aria-labelledby="automation-overview-title">
        <div>
          <p className={styles['eyebrow']}>从构想到稳定运行</p>
          <h2 id="automation-overview-title">把流程、计划、执行者和运行放回同一个生命周期。</h2>
          <p className={styles['description']}>
            从一个入口设计自动化、安排触发、分配执行资源，并在运行记录中完成审批与协作。
          </p>
        </div>
        <div className={styles['focus-mark']} aria-hidden="true" />
      </section>

      <nav className={styles['lifecycle-grid']} aria-label="自动化生命周期">
        {lifecycleEntries.map(({ path, label, description, icon: Icon }, index) => (
          <Link key={path} to={path} className={styles['lifecycle-card']}>
            <span className={styles['card-index']}>{String(index + 1).padStart(2, '0')}</span>
            <span className={styles['card-icon']} aria-hidden="true"><Icon size={22} /></span>
            <strong>{label}</strong>
            <span>{description}</span>
          </Link>
        ))}
      </nav>
    </PageLayout>
  )
}
