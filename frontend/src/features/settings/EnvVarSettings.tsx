/**
 * 环境变量管理组件 — 查看和编辑运行环境变量。
 */
import React, { useEffect, useState, useCallback } from 'react';
import { listEnvVars, updateEnvVar, testEnvVar, type EnvVarItem } from './envVarApi';
import { useI18nStore } from '@/i18n';
import styles from './EnvVarSettings.module.css';

const CATEGORY_LABELS: Record<string, string> = {
  llm: 'LLM Providers',
  channel: 'Channel Config',
  security: 'Security',
  storage: 'Storage',
  general: 'General',
};

const EnvVarSettings: React.FC = () => {
  // 使用选择器精确订阅，避免整个 store 变化触发重渲染
  const t = useI18nStore(s => s.t);
  const [vars, setVars] = useState<EnvVarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState('');
  const [showSecret, setShowSecret] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [message, setMessage] = useState('');

  const loadVars = useCallback(async () => {
    try {
      setLoading(true);
      const data = await listEnvVars();
      setVars(data);
    } catch {
      // 后端未实现时静默处理
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadVars();
  }, [loadVars]);

  const handleSave = async (name: string) => {
    setSaving(name);
    try {
      await updateEnvVar(name, editValue);
      setMessage(`${name} saved`);
      setEditingKey(null);
      loadVars();
    } catch {
      setMessage(`Failed to save ${name}`);
    } finally {
      setSaving(null);
    }
  };

  const handleTest = async (name: string) => {
    setTesting(name);
    try {
      const result = await testEnvVar(name);
      setMessage(result.success ? `${name}: OK` : `${name}: ${result.message}`);
    } catch {
      setMessage(`Test failed for ${name}`);
    } finally {
      setTesting(null);
    }
  };

  const grouped = vars.reduce<Record<string, EnvVarItem[]>>((acc, v) => {
    const cat = v.category || 'general';
    acc[cat] = acc[cat] || [];
    acc[cat].push(v);
    return acc;
  }, {});

  if (loading) return <div className={styles.container}>{t('app.loading')}</div>;

  return (
    <div className={styles.container}>
      <h2>Environment Variables</h2>
      <p className={styles.hint}>Manage runtime environment variables. Sensitive values are masked.</p>

      {message && <div className={styles.message} onClick={() => setMessage('')}>{message}</div>}

      {Object.entries(grouped).map(([category, items]) => (
        <div key={category} className={styles.categorySection}>
          <h3>{CATEGORY_LABELS[category] || category}</h3>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Value</th>
                <th>Description</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((v) => (
                <tr key={v.name}>
                  <td className={styles.nameCell}>{v.name}</td>
                  <td className={styles.valueCell}>
                    {editingKey === v.name ? (
                      <input
                        className={styles.editInput}
                        type="text"
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        autoFocus
                      />
                    ) : (
                      <span className={styles.value}>
                        {v.is_sensitive && !showSecret[v.name]
                          ? '****'
                          : v.value}
                        {v.is_sensitive && (
                          <button
                            className={styles.revealBtn}
                            onClick={() => setShowSecret((s) => ({ ...s, [v.name]: !s[v.name] }))}
                          >
                            {showSecret[v.name] ? 'Hide' : 'Show'}
                          </button>
                        )}
                      </span>
                    )}
                  </td>
                  <td>{v.description}</td>
                  <td className={styles.actions}>
                    {editingKey === v.name ? (
                      <>
                        <button onClick={() => handleSave(v.name)} disabled={saving === v.name}>
                          {saving === v.name ? '...' : 'Save'}
                        </button>
                        <button onClick={() => setEditingKey(null)}>Cancel</button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => { setEditingKey(v.name); setEditValue(v.value); }}>
                          Edit
                        </button>
                        {v.is_sensitive && (
                          <button onClick={() => handleTest(v.name)} disabled={testing === v.name}>
                            {testing === v.name ? '...' : 'Test'}
                          </button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      {vars.length === 0 && <p className={styles.empty}>No environment variables configured.</p>}
    </div>
  );
};

export default EnvVarSettings;
