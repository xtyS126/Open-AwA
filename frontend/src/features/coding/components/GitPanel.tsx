/**
 * Git 面板组件 — 显示 Git 状态、更改和基本操作。
 */
import React, { useEffect, useState } from 'react';
import { shallow } from 'zustand/shallow';
import { useCodingStore } from '../store/codingStore';
import { codingApi, type GitLogItem } from '../codingApi';
import { appLogger } from '@/shared/utils/logger';
import styles from './GitPanel.module.css';

interface GitPanelProps {
  onFileClick?: (filePath: string) => void
}

const GitPanel: React.FC<GitPanelProps> = ({ onFileClick }) => {
  // 使用选择器 + shallow 浅比较，避免整个 store 变化触发重渲染
  const { gitBranch, gitChanges, setGitStatus, projectDir } = useCodingStore(s => ({
    gitBranch: s.gitBranch,
    gitChanges: s.gitChanges,
    setGitStatus: s.setGitStatus,
    projectDir: s.projectDir,
  }), shallow);
  const [loading, setLoading] = useState(true);
  const [commitMsg, setCommitMsg] = useState('');
  const [log, setLog] = useState<GitLogItem[]>([]);
  const [activeTab, setActiveTab] = useState<'changes' | 'log'>('changes');

  const loadStatus = async () => {
    try {
      setLoading(true);
      const status = await codingApi.gitStatus(projectDir || undefined);
      // 区分联合类型：仅在 is_repo 为 true 时提取 branch/changes
      if (status.is_repo) {
        setGitStatus(status.branch || '', status.changes || []);
      }
      const logData = await codingApi.gitLog(20, projectDir || undefined);
      if (logData.commits) setLog(logData.commits);
    } catch (e) {
      // 状态加载失败时记录警告，避免静默吞异常导致用户无反馈
      appLogger.warning({
        event: 'git_status_load_failed',
        module: 'coding',
        message: '加载 Git 状态失败',
        extra: { error: e instanceof Error ? e.message : String(e) },
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, [projectDir]);

  const handleCommit = async () => {
    if (!commitMsg.trim()) return;
    try {
      await codingApi.gitCommit(commitMsg, undefined, projectDir || undefined);
      setCommitMsg('');
      await loadStatus();
    } catch (e) {
      appLogger.error({
        event: 'git_commit_failed',
        module: 'coding',
        message: 'Git 提交失败',
        extra: { error: e instanceof Error ? e.message : String(e) },
      });
    }
  };

  if (loading) return <div className={styles.panel}><p className={styles.loading}>加载中...</p></div>;

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <span className={styles.branch}>git:{gitBranch || 'unknown'}</span>
        <button className={styles.refreshBtn} onClick={loadStatus}>↻</button>
      </div>

      <div className={styles.tabs}>
        <button
          className={`${styles.tab} ${activeTab === 'changes' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('changes')}
        >
          更改 ({gitChanges.length})
        </button>
        <button
          className={`${styles.tab} ${activeTab === 'log' ? styles.tabActive : ''}`}
          onClick={() => setActiveTab('log')}
        >
          历史
        </button>
      </div>

      {activeTab === 'changes' && (
        <div className={styles.changes}>
          {gitChanges.length === 0 ? (
            <p className={styles.clean}>工作区干净</p>
          ) : (
            gitChanges.map((c, i) => (
              <div
                key={i}
                className={styles.change}
                onClick={() => onFileClick?.(c.file)}
                style={{ cursor: onFileClick ? 'pointer' : undefined }}
              >
                <span className={c.status.includes('M') ? styles.modified : styles.added}>
                  {c.status}
                </span>
                <span className={styles.file}>{c.file}</span>
              </div>
            ))
          )}
          {gitChanges.length > 0 && (
            <div className={styles.commitArea}>
              <input
                type="text"
                placeholder="提交信息..."
                value={commitMsg}
                onChange={(e) => setCommitMsg(e.target.value)}
                className={styles.commitInput}
              />
              <button className={styles.commitBtn} onClick={handleCommit}>提交</button>
            </div>
          )}
        </div>
      )}

      {activeTab === 'log' && (
        <div className={styles.log}>
          {log.map((c, i) => (
            <div key={i} className={styles.logItem}>
              <span className={styles.hash}>{c.hash}</span>
              <span className={styles.msg}>{c.message}</span>
              <span className={styles.author}>{c.author} · {c.date}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default React.memo(GitPanel);
