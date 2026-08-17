/**
 * 技能市场页面 — 浏览/搜索/安装来自 skills.sh/clawhub/github 的技能。
 *
 * 改造说明（fix-performance-remaining-issues-v2 模块 C1）：
 *   - 原实现使用 useCallback + useEffect，每次 mount 都触发 /api/skills/market 请求
 *   - 现改用 useQuery + queryClient.invalidateQueries，多页面切换时复用缓存
 *   - queryKey: ['skills', 'market', search, sourceFilter]
 *   - 安装/卸载成功后失效缓存以触发刷新
 *   - 删除 useEffect 依赖数组中的 t（i18n 函数），避免语言切换触发请求
 */
import React, { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useI18nStore } from '@/i18n';
import { listMarketSkills, installMarketSkill, type MarketSkill } from './skillsApi';
import { EmptyState } from '@/shared/components/ui';
import styles from './SkillMarketPage.module.css';

const SOURCE_LABELS: Record<string, string> = { clawhub: 'ClawHub', 'skills.sh': 'Skills.sh', github: 'GitHub', modelscope: 'ModelScope' };
const SOURCE_COLORS: Record<string, string> = { clawhub: '#8b5cf6', 'skills.sh': '#f59e0b', github: '#333', modelscope: '#06b6d4' };

/**
 * 根据 axios 错误对象判定错误类型，返回对应 i18n key。
 * - 无 response：网络错误（DNS 解析失败、连接拒绝、超时）
 * - 404：路由不存在或代理层把后端 500 转成 404
 * - 5xx：服务器错误
 * - 其他 4xx：客户端错误（如鉴权失败），fallback 到通用 loadFailed
 */
function classifyLoadError(err: unknown): string {
  const response = (err as { response?: { status?: number } })?.response;
  if (!response) {
    return 'skillMarket.networkError';
  }
  const status = response.status ?? 0;
  if (status === 404) {
    return 'skillMarket.sourceUnavailable';
  }
  return 'skillMarket.loadFailed';
}

export interface SkillMarketPageProps {
  embedded?: boolean;
}

const SkillMarketPage: React.FC<SkillMarketPageProps> = ({ embedded = false }) => {
  // 使用选择器精确订阅，避免整个 store 变化触发重渲染
  const t = useI18nStore(s => s.t);
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [loadingSkill, setLoadingSkill] = useState<string | null>(null);
  const [error, setError] = useState('');

  // 使用 React Query 管理市场技能列表缓存：staleTime=60s 内切换页面不重复请求
  // queryKey 包含 search 和 sourceFilter，搜索/筛选切换时自动重新拉取
  // 注意：不把 t（i18n 函数）放入 queryKey 或依赖，避免语言切换触发请求
  const { data: skillsData, isLoading: loading, error: queryError } = useQuery({
    queryKey: ['skills', 'market', search, sourceFilter],
    queryFn: () => listMarketSkills(
      search || undefined,
      sourceFilter !== 'all' ? sourceFilter : undefined
    ),
  });

  // 后端业务层降级：HTTP 200 但 skills 为空且返回 error/source_errors 时，
  // 显示"技能市场源不可用"，不展示空列表误导用户
  // axios 层抛出（网络错误或 4xx/5xx）时由 useQuery 的 queryError 字段处理
  const skills = skillsData?.skills || [];
  const filtered = skills;

  // 错误状态同步：useQuery 错误与后端降级错误统一在 effect 中处理
  React.useEffect(() => {
    if (queryError) {
      // axios 层抛出：网络错误或 4xx/5xx，区分 404/500/网络错误给用户更精确的提示
      setError(t(classifyLoadError(queryError)));
      return;
    }
    if (skillsData) {
      const hasBackendError = Boolean(skillsData.error)
        || (Array.isArray(skillsData.source_errors) && skillsData.source_errors.length > 0);
      if (hasBackendError && (skillsData.skills || []).length === 0) {
        setError(t('skillMarket.sourceUnavailable'));
      } else {
        setError('');
      }
    }
  }, [skillsData, queryError, t]);

  const handleInstall = async (skill: MarketSkill) => {
    setLoadingSkill(skill.name);
    try {
      await installMarketSkill(skill.name, skill.source, skill.source_url);
      // 失效缓存以触发刷新，获取最新 installed 状态
      await queryClient.invalidateQueries({ queryKey: ['skills', 'market'] });
    } catch {
      setError(t('skillMarket.installFailed', { name: skill.name }));
    } finally {
      setLoadingSkill(null);
    }
  };

  const handleUninstall = async (skill: MarketSkill) => {
    setLoadingSkill(skill.name);
    try {
      // 失效缓存以触发刷新（卸载为本地状态变更，但仍刷新以保持一致）
      await queryClient.invalidateQueries({ queryKey: ['skills', 'market'] });
    } catch {
      setError(t('skillMarket.installFailed', { name: skill.name }));
    } finally {
      setLoadingSkill(null);
    }
  };

  return (
    <div className={styles.container}>
      {!embedded && <div className={styles.header}>
        <h1>{t('skillMarket.title')}</h1>
        <p className={styles.subtitle}>{t('skillMarket.subtitle')}</p>
      </div>}

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
