/**
 * Coding 模式主页面 — 三面板 IDE 布局。
 * 左侧：文件树 | 中间：编辑器 | 右侧：聊天面板
 * 底部：Git 面板
 */
import React, { useEffect, useState, useCallback } from 'react';
import FileTree from './components/FileTree';
import EditorPane from './components/EditorPane';
import GitPanel from './components/GitPanel';
import { useCodingStore } from './store/codingStore';
import { codingApi } from './codingApi';
import styles from './CodingPage.module.css';

const CodingPage: React.FC = () => {
  const { setProjectDir, projectDir, ccModeEnabled, toggleCCMode } = useCodingStore();
  const [showGit, setShowGit] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [layouts, setLayouts] = useState({
    fileTreeWidth: 240,
    gitPanelHeight: 180,
  });

  useEffect(() => {
    // 默认使用当前项目目录
    if (!projectDir) {
      setProjectDir('/');
    }
  }, []);

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return;
    try {
      // 尝试定义搜索
      const defs = await codingApi.searchDefinitions(searchQuery, projectDir || undefined);
      if (defs.results?.length > 0) {
        setSearchResults(defs.results);
        return;
      }
      // 回退到文本搜索
      const pattern = await codingApi.searchPattern(searchQuery, projectDir || undefined);
      setSearchResults(pattern.results || []);
    } catch (e) {
      console.error('Search failed:', e);
    }
  }, [searchQuery, projectDir]);

  const handleResultClick = async (result: any) => {
    if (result.file) {
      try {
        const data = await codingApi.readFile(result.file, projectDir || undefined);
        if (data.content !== undefined) {
          useCodingStore.getState().openFile({
            path: result.file,
            name: result.file.split('/').pop() || result.file,
            content: data.content,
            isDirty: false,
            language: '',
          });
        }
      } catch (e) {
        /* ignore */
      }
    }
  };

  return (
    <div className={styles.container}>
      {/* 工具栏 */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <span className={styles.title}>Coding 模式</span>
          <button
            className={`${styles.ccToggle} ${ccModeEnabled ? styles.ccActive : ''}`}
            onClick={toggleCCMode}
            title={ccModeEnabled ? 'Claude Code 模式已启用' : '启用 Claude Code 模式'}
          >
            {ccModeEnabled ? 'CC ON' : 'CC OFF'}
          </button>
          <button
            className={styles.gitToggle}
            onClick={() => setShowGit(!showGit)}
          >
            Git
          </button>
        </div>
        <div className={styles.toolbarCenter}>
          <input
            type="text"
            className={styles.searchInput}
            placeholder="搜索函数/类/文本..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          />
        </div>
        <div className={styles.toolbarRight}>
          <span className={styles.projectLabel}>
            {projectDir || '/'}
          </span>
        </div>
      </div>

      {/* 主面板 */}
      <div className={styles.mainPanel}>
        {/* 左侧：文件树 */}
        <div className={styles.leftPanel} style={{ width: layouts.fileTreeWidth }}>
          <FileTree />
        </div>

        {/* 中间：编辑器 */}
        <div className={styles.centerPanel}>
          <EditorPane />
          {/* 搜索结果覆盖层 */}
          {searchResults.length > 0 && (
            <div className={styles.searchResults}>
              <div className={styles.searchHeader}>
                搜索结果 ({searchResults.length})
                <button onClick={() => setSearchResults([])}>×</button>
              </div>
              {searchResults.slice(0, 50).map((r, i) => (
                <div
                  key={i}
                  className={styles.searchItem}
                  onClick={() => handleResultClick(r)}
                >
                  <span className={styles.searchType}>
                    {r.type || r.match ? 'match' : 'def'}
                  </span>
                  <span className={styles.searchFile}>{r.file}</span>
                  <span className={styles.searchLine}>:{r.line}</span>
                  {(r.name || r.match) && (
                    <span className={styles.searchName}>{r.name || r.match}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 右侧：聊天面板（使用 iframe 嵌入聊天页面）*/}
        <div className={styles.rightPanel}>
          <div className={styles.chatHeader}>
            聊天
          </div>
          <div className={styles.chatContent}>
            <p className={styles.chatPlaceholder}>
              Coding 模式聊天面板
            </p>
            <textarea
              className={styles.chatInput}
              placeholder="向 Agent 提问（例如：'分析 src/core 的架构'）..."
              rows={3}
            />
          </div>
        </div>
      </div>

      {/* 底部：Git 面板 */}
      {showGit && (
        <div className={styles.bottomPanel} style={{ height: layouts.gitPanelHeight }}>
          <GitPanel />
        </div>
      )}
    </div>
  );
};

export default React.memo(CodingPage);
