import { ExtractionLog } from '../services/experiencesApi'

interface Props {
  logs: ExtractionLog[]
  onReview: (id: number, approved: boolean) => void
}

function ExtractionLogTable({ logs, onReview }: Props) {
  const getTriggerLabel = (trigger: string): string => {
    const labels: Record<string, string> = {
      success: '任务成功',
      failure: '任务失败',
      manual: '手动触发',
      periodic: '定期扫描'
    }
    return labels[trigger] || trigger
  }

  return (
    <div className="logs-table-container">
      <table className="logs-table">
        <thead>
          <tr>
            <th>会话ID</th>
            <th>任务摘要</th>
            <th>触发类型</th>
            <th>质量评分</th>
            <th>审核状态</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {logs.map((log) => (
            <tr key={log.id}>
              <td className="session-id">{log.session_id}</td>
              <td className="task-summary">{log.task_summary}</td>
              <td>
                <span className={`trigger-badge ${log.trigger}`}>
                  {getTriggerLabel(log.trigger)}
                </span>
              </td>
              <td>{(log.quality * 100).toFixed(0)}%</td>
              <td>
                <span className={`review-status ${log.reviewed ? 'reviewed' : 'pending'}`}>
                  {log.reviewed ? '已审核' : '待审核'}
                </span>
              </td>
              <td>{new Date(log.created_at).toLocaleString()}</td>
              <td>
                {!log.reviewed && (
                  <div className="action-buttons">
                    <button
                      className="btn-approve"
                      onClick={() => onReview(log.id, true)}
                    >
                      批准
                    </button>
                    <button
                      className="btn-reject"
                      onClick={() => onReview(log.id, false)}
                    >
                      拒绝
                    </button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {logs.length === 0 && (
        <div className="empty-state">暂无提取日志</div>
      )}
    </div>
  )
}

export default ExtractionLogTable
