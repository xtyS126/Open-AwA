/**
 * 数据导出面板组件
 */
import styles from '../SettingsPage.module.css'

interface ExportPanelProps {
  /** 开始时间 */
  exportStartTime: string
  /** 结束时间 */
  exportEndTime: string
  /** 是否正在导出 */
  exportingRecords: boolean

  /** 开始时间变更回调 */
  onExportStartTimeChange: (time: string) => void
  /** 结束时间变更回调 */
  onExportEndTimeChange: (time: string) => void
  /** 导出回调 */
  onExportRecords: () => void
}

export function ExportPanel({
  exportStartTime,
  exportEndTime,
  exportingRecords,
  onExportStartTimeChange,
  onExportEndTimeChange,
  onExportRecords,
}: ExportPanelProps) {
  return (
    <div className={styles['collection-export-panel']}>
      <h3>导出 JSONL</h3>
      <div className={styles['form-row']}>
        <div className={styles['form-group']}>
          <label>开始时间（可选）</label>
          <input
            type="datetime-local"
            value={exportStartTime}
            onChange={(e) => onExportStartTimeChange(e.target.value)}
          />
        </div>
        <div className={styles['form-group']}>
          <label>结束时间（可选）</label>
          <input
            type="datetime-local"
            value={exportEndTime}
            onChange={(e) => onExportEndTimeChange(e.target.value)}
          />
        </div>
      </div>
      <button
        className={`btn btn-primary`}
        onClick={onExportRecords}
        disabled={exportingRecords}
      >
        {exportingRecords ? '导出中...' : '导出数据集'}
      </button>
    </div>
  )
}

export default ExportPanel
