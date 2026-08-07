/**
 * 技能市场页面 — 浏览/搜索/安装来自 skills.sh/clawhub/github 的技能。
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useI18nStore } from '@/i18n';
import { listMarketSkills, installMarketSkill, type MarketSkill } from './skillsApi';
import { EmptyState } from '@/shared/components/ui';
import styles from './SkillMarketPage.module.css';

const SOURCE_LABELS: Record<string, string> = { clawhub: 'ClawHub', 'skills.sh': 'Skills.sh', github: 'GitHub', modelscope: 'ModelScope' };
const SOURCE_COLORS: Record<string, string> = { clawhub: '#8b5cf6', 'skills.sh': '#f59e0b', github: '#333', modelscope: '#06b6d4' };

const SkillMarketPage: React.FC = () => {
  // 使用选择器精确订阅，避免整个 store 变化触发重渲染
  const t = useI18nStore(s => s.t);
  const [skills, setSkills] = useState<MarketSkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [loadingSkill, setLoadingSkill] = useState<string | null>(null);
  const [error, setError] = useState('');

  const loadSkills = useCallback(async () => {
    try {
      setLoading(true);
      const data = await listMarketSkills(
        search || undefined,
        sourceFilter !== 'all' ? sourceFilter : undefined
      );
      setSkills(data.skills || []);
      setError('');
    } catch {
      // 加载失败显示错误条（对齐 handleInstall 的错误处理），不显示空市场误导用户
      setError(t('skillMarket.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [search, sourceFilter, t]);

  useEffect(() => {
    loadSkills();
  }, [loadSkills]);

  const filtered = skills;

  const handleInstall = async (skill: MarketSkill) => {
    setLoadingSkill(skill.name);
    try {
      await installMarketSkill(skill.name, skill.source, skill.source_url);
      setSkills((prev) => prev.map((s) => s.name === skill.name ? { ...s, installed: true } : s));
    } catch {
      setError(t('skillMarket.installFailed', { name: skill.name }));
    } finally {
      setLoadingSkill(null);
    }
  };

  const handleUninstall = async (skill: MarketSkill) => {
    setLoadingSkill(skill.name);
    try {
      setSkills((prev) => prev.map((s) => s.name === skill.name ? { ...s, installed: false } : s));
    } catch {
      setError(t('skillMarket.installFailed', { name: skill.name }));
    } finally {
      setLoadingSkill(null);
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>{t('skillMarket.title')}</h1>
        <p className={styles.subtitle}>{t('skillMarket.subtitle')}</p>
      </div>

      {error && <div className={styles.error}>{error}<button onClick={() => setError('')}>x</button></div>}

      <div className={styles.toolbar}>
        <input
          type="text"
          className={styles.search}
          placeholder={t('skillMarket.searchPlaceholder')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className={styles.filters}>
          {['all', 'clawhub', 'skills.sh', 'github'].map((s) => (
            <button
              key={s}
              className={`${styles.filter} ${sourceFilter === s ? styles.filterActive : ''}`}
              onClick={() => setSourceFilter(s)}
            >
              {s === 'all' ? t('skillMarket.filterAll') : (SOURCE_LABELS[s] || s)}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.grid}>
        {filtered.map((skill) => (
          <div key={skill.name} className={styles.card}>
            <div className={styles.cardHeader}>
              <h3>{skill.name}</h3>
              <span
                className={styles.source}
                style={{ background: SOURCE_COLORS[skill.source] || '#666' }}
              >
                {SOURCE_LABELS[skill.source] || skill.source}
              </span>
            </div>
            <p className={styles.desc}>{skill.description}</p>
            <div className={styles.meta}>
              <span>v{skill.version}</span>
              <span>by {skill.author}</span>
              <span>{t('skillMarket.downloads', { count: String(skill.downloads) })}</span>
            </div>
            <div className={styles.actions}>
              {skill.installed ? (
                <button
                  className={styles.uninstallBtn}
                  onClick={() => handleUninstall(skill)}
                  disabled={loadingSkill === skill.name}
                >
                  {loadingSkill === skill.name ? t('skillMarket.uninstalling') : t('skillMarket.installed')}
                </button>
              ) : (
                <button
                  className={styles.installBtn}
                  onClick={() => handleInstall(skill)}
                  disabled={loadingSkill === skill.name}
                >
                  {loadingSkill === skill.name ? t('skillMarket.installing') : t('skillMarket.install')}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {loading && filtered.length === 0 && (
        <p className={styles.empty}>{t('app.loading')}</p>
      )}
      {!loading && !error && filtered.length === 0 && (
        <EmptyState title={t('skillMarket.empty')} />
      )}
    </div>
  );
};

export default SkillMarketPage;
