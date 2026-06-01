/**
 * 技能市场页面 — 浏览/搜索/安装来自 skills.sh/clawhub/github 的技能。
 */
import React, { useState } from 'react';
import styles from './SkillMarketPage.module.css';

interface MarketSkill {
  name: string;
  description: string;
  version: string;
  source: string;
  sourceUrl: string;
  author: string;
  downloads: number;
  installed: boolean;
}

// 模拟市场数据（实际应通过后端 API 获取）
const MOCK_SKILLS: MarketSkill[] = [
  { name: 'pdf', description: 'PDF文档读取、提取、合并、拆分、OCR', version: '1.0.0', source: 'clawhub', sourceUrl: 'https://clawhub.ai/skills/pdf', author: 'anthropics', downloads: 15200, installed: true },
  { name: 'docx', description: 'Word文档创建、编辑、格式化', version: '1.1.0', source: 'clawhub', sourceUrl: 'https://clawhub.ai/skills/docx', author: 'anthropics', downloads: 12300, installed: true },
  { name: 'xlsx', description: 'Excel表格操作、公式、数据分析', version: '1.0.0', source: 'clawhub', sourceUrl: 'https://clawhub.ai/skills/xlsx', author: 'anthropics', downloads: 9800, installed: true },
  { name: 'pptx', description: 'PPT演示文稿创建和编辑', version: '1.0.0', source: 'clawhub', sourceUrl: 'https://clawhub.ai/skills/pptx', author: 'anthropics', downloads: 8700, installed: false },
  { name: 'browser-cdp', description: 'Chrome DevTools Protocol浏览器自动化', version: '1.2.0', source: 'skills.sh', sourceUrl: 'https://skills.sh/skills/browser-cdp', author: 'community', downloads: 6500, installed: false },
  { name: 'find-skills', description: '搜索和发现新的技能', version: '1.0.0', source: 'skills.sh', sourceUrl: 'https://skills.sh/skills/find-skills', author: 'community', downloads: 5400, installed: false },
  { name: 'news', description: '新闻聚合和摘要', version: '1.0.0', source: 'clawhub', sourceUrl: 'https://clawhub.ai/skills/news', author: 'community', downloads: 4100, installed: false },
  { name: 'himalaya', description: '邮件管理 IMAP/SMTP', version: '1.0.0', source: 'clawhub', sourceUrl: 'https://clawhub.ai/skills/himalaya', author: 'openclaw', downloads: 3200, installed: true },
  { name: 'skill-creator', description: '创建和打包自定义技能', version: '1.1.0', source: 'skills.sh', sourceUrl: 'https://skills.sh/skills/skill-creator', author: 'anthropics', downloads: 2100, installed: false },
  { name: 'webapp-testing', description: '使用Playwright测试Web应用', version: '1.0.0', source: 'clawhub', sourceUrl: 'https://clawhub.ai/skills/webapp-testing', author: 'community', downloads: 1800, installed: false },
];

const SOURCE_LABELS: Record<string, string> = { clawhub: 'ClawHub', 'skills.sh': 'Skills.sh', github: 'GitHub', modelscope: 'ModelScope' };
const SOURCE_COLORS: Record<string, string> = { clawhub: '#8b5cf6', 'skills.sh': '#f59e0b', github: '#333', modelscope: '#06b6d4' };

const SkillMarketPage: React.FC = () => {
  const [skills, setSkills] = useState<MarketSkill[]>(MOCK_SKILLS);
  const [search, setSearch] = useState('');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [loadingSkill, setLoadingSkill] = useState<string | null>(null);
  const [error, setError] = useState('');

  const filtered = skills.filter((s) => {
    if (search && !s.name.includes(search) && !s.description.includes(search)) return false;
    if (sourceFilter !== 'all' && s.source !== sourceFilter) return false;
    return true;
  });

  const handleInstall = async (skill: MarketSkill) => {
    setLoadingSkill(skill.name);
    try {
      // 调用后端技能导入 API（后续对接真实后端时启用）
      setSkills((prev) => prev.map((s) => s.name === skill.name ? { ...s, installed: true } : s));
    } catch (e) {
      setError(`安装 ${skill.name} 失败`);
    } finally {
      setLoadingSkill(null);
    }
  };

  const handleUninstall = async (skill: MarketSkill) => {
    setLoadingSkill(skill.name);
    // 调用后端卸载 API（后续对接真实后端时启用）
    setSkills((prev) => prev.map((s) => s.name === skill.name ? { ...s, installed: false } : s));
    setLoadingSkill(null);
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1>技能市场</h1>
        <p className={styles.subtitle}>浏览和安装来自 ClawHub、Skills.sh、GitHub 的技能</p>
      </div>

      {error && <div className={styles.error}>{error}<button onClick={() => setError('')}>x</button></div>}

      <div className={styles.toolbar}>
        <input
          type="text"
          className={styles.search}
          placeholder="搜索技能..."
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
              {s === 'all' ? '全部' : (SOURCE_LABELS[s] || s)}
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
              <span>{skill.downloads.toLocaleString()} 次下载</span>
            </div>
            <div className={styles.actions}>
              {skill.installed ? (
                <button
                  className={styles.uninstallBtn}
                  onClick={() => handleUninstall(skill)}
                  disabled={loadingSkill === skill.name}
                >
                  {loadingSkill === skill.name ? '卸载中...' : '已安装 (卸载)'}
                </button>
              ) : (
                <button
                  className={styles.installBtn}
                  onClick={() => handleInstall(skill)}
                  disabled={loadingSkill === skill.name}
                >
                  {loadingSkill === skill.name ? '安装中...' : '安装'}
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {filtered.length === 0 && (
        <p className={styles.empty}>未找到匹配的技能</p>
      )}
    </div>
  );
};

export default SkillMarketPage;
