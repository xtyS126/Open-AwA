/**
 * 工作区管理页面 — 多智能体工作区的创建、切换和管理。
 */
import React, { useEffect, useState } from 'react';
import { useWorkspaceStore, type Workspace } from './store/workspaceStore';
import { workspaceApi } from './workspaceApi';
import styles from './WorkspacePage.module.css';

const AGENT_TYPES: Record<string, string> = {
  default: '通用助手',
  coding: '代码助手',
  qa: '问答助手',
  writer: '写作助手',
  planner: '规划助手',
  custom: '自定义',
};

const WorkspacePage: React.FC = () => {
  const {
    workspaces,
    currentWorkspaceId,
    setWorkspaces,
    setCurrentWorkspace,
  } = useWorkspaceStore();

  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createDesc, setCreateDesc] = useState('');
  const [createType, setCreateType] = useState('default');
  const [error, setError] = useState('');

  useEffect(() => {
    loadWorkspaces();
  }, []);

  const loadWorkspaces = async () => {
    try {
      setLoading(true);
      const data = await workspaceApi.list();
      setWorkspaces(data.workspaces);
    } catch (e) {
      setError('加载工作区列表失败');
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async () => {
    if (!createName.trim()) {
      setError('请输入工作区名称');
      return;
    }
    try {
      await workspaceApi.create({
        name: createName.trim(),
        description: createDesc.trim(),
        agent_type: createType,
      });
      setShowCreate(false);
      setCreateName('');
      setCreateDesc('');
      setError('');
      await loadWorkspaces();
    } catch (e: any) {
      setError(e?.response?.data?.detail || '创建工作区失败');
    }
  };

  const handleSwitch = async (ws: Workspace) => {
    try {
      setCurrentWorkspace(ws.id);
    } catch (e) {
      setError('切换工作区失败');
    }
  };

  const handleDelete = async (ws: Workspace) => {
    if (ws.is_default) {
      setError('默认工作区不可删除');
      return;
    }
    if (!confirm(`确认删除工作区 "${ws.name}"？此操作不可撤销。`)) return;
    try {
      await workspaceApi.delete(ws.id);
      await loadWorkspaces();
    } catch (e: any) {
      setError(e?.response?.data?.detail || '删除工作区失败');
    }
  };

  const handleToggle = async (ws: Workspace) => {
    try {
      await workspaceApi.update(ws.id, { is_enabled: !ws.is_enabled });
      await loadWorkspaces();
    } catch (e: any) {
      setError(e?.response?.data?.detail || '更新工作区失败');
    }
  };

  if (loading) {
    return <div className={styles.container}><p>加载中...</p></div>;
  }

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>智能体工作区</h1>
        <button className={styles.createBtn} onClick={() => setShowCreate(true)}>
          + 创建智能体
        </button>
      </div>

      {error && (
        <div className={styles.error}>
          {error}
          <button onClick={() => setError('')}>x</button>
        </div>
      )}

      {showCreate && (
        <div className={styles.createModal}>
          <div className={styles.createContent}>
            <h2>创建新智能体</h2>
            <label>
              名称
              <input
                type="text"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                placeholder="例如：代码助手"
              />
            </label>
            <label>
              描述
              <input
                type="text"
                value={createDesc}
                onChange={(e) => setCreateDesc(e.target.value)}
                placeholder="描述这个智能体的专长和用途"
              />
            </label>
            <label>
              类型
              <select value={createType} onChange={(e) => setCreateType(e.target.value)}>
                {Object.entries(AGENT_TYPES).map(([key, label]) => (
                  <option key={key} value={key}>{label}</option>
                ))}
              </select>
            </label>
            <div className={styles.createActions}>
              <button onClick={handleCreate}>创建</button>
              <button className={styles.cancelBtn} onClick={() => setShowCreate(false)}>取消</button>
            </div>
          </div>
        </div>
      )}

      <div className={styles.list}>
        {workspaces.length === 0 ? (
          <p className={styles.empty}>暂无工作区，请创建一个</p>
        ) : (
          workspaces.map((ws) => (
            <div
              key={ws.id}
              className={`${styles.card} ${ws.id === currentWorkspaceId ? styles.active : ''} ${!ws.is_enabled ? styles.disabled : ''}`}
            >
              <div className={styles.cardInfo}>
                <div className={styles.cardHeader}>
                  <h3>{ws.name}</h3>
                  {ws.is_default && <span className={styles.badge}>默认</span>}
                  {!ws.is_enabled && <span className={styles.badgeDisabled}>已禁用</span>}
                </div>
                <p className={styles.cardDesc}>{ws.description || '无描述'}</p>
                <div className={styles.cardMeta}>
                  <span>类型: {AGENT_TYPES[ws.agent_type] || ws.agent_type}</span>
                  <span>技能: {ws.skills_count} 个</span>
                  <span>频道: {ws.channels_count} 个</span>
                </div>
              </div>
              <div className={styles.cardActions}>
                {ws.id !== currentWorkspaceId && ws.is_enabled && (
                  <button className={styles.switchBtn} onClick={() => handleSwitch(ws)}>
                    切换
                  </button>
                )}
                {ws.id === currentWorkspaceId && (
                  <span className={styles.currentLabel}>当前</span>
                )}
                <button
                  className={styles.toggleBtn}
                  onClick={() => handleToggle(ws)}
                >
                  {ws.is_enabled ? '禁用' : '启用'}
                </button>
                {!ws.is_default && (
                  <button
                    className={styles.deleteBtn}
                    onClick={() => handleDelete(ws)}
                  >
                    删除
                  </button>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default WorkspacePage;
