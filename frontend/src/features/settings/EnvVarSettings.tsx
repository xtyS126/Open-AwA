/**
 * 环境变量管理组件 — 查看和编辑运行环境变量。
 */
import React, { useEffect, useState, useCallback } from 'react';
import { listEnvVars, updateEnvVar, testEnvVar, type EnvVarItem } from './envVarApi';
import { useI18nStore } from '@/i18n';
import styles from './EnvVarSettings.module.css';

/** 环境变量分类 → i18n key 映射 */
const CATEGORY_KEYS: Record<string, string> = {
  llm: 'envVars.category.llm',
  channel: 'envVars.category.channel',
  security: 'envVars.category.security',
  storage: 'envVars.category.storage',
  general: 'envVars.category.general',
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
      setMessage(t('envVars.saved', { name }));
      setEditingKey(null);
      loadVars();
    } catch {
      setMessage(t('envVars.saveFailed', { name }));
    } finally {
      setSaving(null);
    }
  };

  const handleTest = async (name: string) => {
    setTesting(name);
    try {
      const result = await testEnvVar(name);
      setMessage(result.success
        ? t('envVars.testOk', { name })
        : t('envVars.testResult', { name, message: result.message }));
    } catch {
      setMessage(t('envVars.testError', { name }));
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
      <h2>{t('envVars.title')}</h2>
      <p className={styles.hint}>{t('envVars.hint')}</p>

      {message && <div className={styles.message} onClick={() => setMessage('')}>{message}</div>}

      {Object.entries(grouped).map(([category, items]) => (
        <div key={category} className={styles.categorySection}>
          <h3>{CATEGORY_KEYS[category] ? t(CATEGORY_KEYS[category]) : category}</h3>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>{t('envVars.col.name')}</th>
                <th>{t('envVars.col.value')}</th>
                <th>{t('envVars.col.description')}</th>
                <th>{t('envVars.col.actions')}</th>
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
                            {showSecret[v.name] ? t('envVars.hide') : t('envVars.show')}
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
                          {saving === v.name ? '...' : t('envVars.save')}
                        </button>
                        <button onClick={() => setEditingKey(null)}>{t('envVars.cancel')}</button>
                      </>
                    ) : (
                      <>
                        <button onClick={() => { setEditingKey(v.name); setEditValue(v.value); }}>
                          {t('envVars.edit')}
                        </button>
                        {v.is_sensitive && (
                          <button onClick={() => handleTest(v.name)} disabled={testing === v.name}>
                            {testing === v.name ? '...' : t('envVars.test')}
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

      {vars.length === 0 && <p className={styles.empty}>{t('envVars.empty')}</p>}
    </div>
  );
};

export default EnvVarSettings;
