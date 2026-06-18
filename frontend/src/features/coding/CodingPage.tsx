/**
 * Coding 模式主页面 — 三面板 IDE 布局。
 * 左侧：文件树 | 中间：编辑器/Diff 视图 | 右侧：Coding 聊天助手
 * 底部：Git 面板
 */
import React, { useEffect, useState, useCallback } from 'react'
import FileTree from './components/FileTree'
import EditorPane from './components/EditorPane'
import DiffView from './components/DiffView'
import GitPanel from './components/GitPanel'
import CodingChatPanel from './components/CodingChatPanel'
import TerminalPanel from './components/TerminalPanel'
import ModeSwitcher, { type ExecutionMode } from './components/ModeSwitcher'
import { useCodingStore } from './store/codingStore'
import { codingApi } from './codingApi'
import { appLogger } from '@/shared/utils/logger'
import styles from './CodingPage.module.css'

const CodingPage: React.FC = () => {
  const {
    setProjectDir, projectDir, ccModeEnabled, toggleCCMode,
    diffMode, setDiffMode, openFiles, activeFilePath,
  } = useCodingStore()
  const [showGit, setShowGit] = useState(false)
  const [showTerminal, setShowTerminal] = useState(false)
  const [executionMode, setExecutionMode] = useState<ExecutionMode>('solo')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [diffData, setDiffData] = useState<{ original: string; modified: string; filePath: string } | null>(null)
  const [layouts] = useState({
    fileTreeWidth: 240,
    gitPanelHeight: 180,
    terminalPanelHeight: 220,
  })

  useEffect(() => {
    if (!projectDir) {
      setProjectDir('/')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 同步 CC 模式到后端
  useEffect(() => {
    codingApi.toggleCCMode(ccModeEnabled).catch((error) => {
      appLogger.error({ event: 'cc_mode_sync_failed', module: 'coding', message: 'CC模式同步失败', extra: { error: error instanceof Error ? error.message : String(error) } })
    })
  }, [ccModeEnabled])

  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim()) return
    try {
      const defs = await codingApi.searchDefinitions(searchQuery, projectDir || undefined)
      if (defs.results?.length > 0) {
        setSearchResults(defs.results)
        return
      }
      const pattern = await codingApi.searchPattern(searchQuery, projectDir || undefined)
      setSearchResults(pattern.results || [])
    } catch (e) {
      appLogger.error({ event: 'search_failed', module: 'coding', message: String(e), extra: e instanceof Error ? { stack: e.stack } : undefined })
    }
  }, [searchQuery, projectDir])

  const handleResultClick = async (result: any) => {
    if (result.file) {
      try {
        const data = await codingApi.readFile(result.file, projectDir || undefined)
        if (data.content !== undefined) {
          useCodingStore.getState().openFile({
            path: result.file,
            name: result.file.split('/').pop() || result.file,
            content: data.content,
            isDirty: false,
            language: '',
          })
        }
      } catch (e) {
        /* ignore */
      }
    }
  }

  // Git 文件点击查看 diff
  const handleGitFileClick = useCallback(async (filePath: string) => {
    try {
      const diffResult = await codingApi.gitDiff(filePath, false, projectDir || undefined)
      const activeFile = openFiles.find((f) => f.path === filePath)
      const currentContent = activeFile?.content || ''
      // 使用 Git diff API 返回的原始内容，若不可用则回退到当前内容
      const originalContent = (diffResult && diffResult.original) || currentContent

      setDiffData({
        original: originalContent,
        modified: currentContent,
        filePath,
      })
      setDiffMode(true)
    } catch (e) {
      appLogger.error({ event: 'diff_fetch_failed', module: 'coding', message: String(e), extra: e instanceof Error ? { stack: e.stack } : undefined })
    }
  }, [projectDir, openFiles, setDiffMode])

  const handleAcceptDiff = useCallback(async () => {
    setDiffMode(false)
    setDiffData(null)
  }, [setDiffMode])

  const handleRejectDiff = useCallback(() => {
    setDiffMode(false)
    setDiffData(null)
  }, [setDiffMode])

  const activeFile = openFiles.find((f) => f.path === activeFilePath)

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
            className={`${styles.gitToggle} ${showTerminal ? styles.gitActive : ''}`}
            onClick={() => setShowTerminal(!showTerminal)}
            title={showTerminal ? '隐藏终端面板' : '显示终端面板'}
          >
            终端
          </button>
          <button
            className={`${styles.gitToggle} ${showGit ? styles.gitActive : ''}`}
            onClick={() => setShowGit(!showGit)}
          >
            Git
          </button>
          <ModeSwitcher mode={executionMode} onModeChange={setExecutionMode} />
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

        {/* 中间：编辑器或 Diff 视图 */}
        <div className={styles.centerPanel}>
          {diffMode && diffData ? (
            <DiffView
              original={diffData.original}
              modified={diffData.modified}
              filePath={diffData.filePath}
              language={activeFile?.language}
              onAccept={handleAcceptDiff}
              onReject={handleRejectDiff}
            />
          ) : (
            <EditorPane />
          )}
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

        {/* 右侧：Coding 聊天助手面板 */}
        <div className={styles.rightPanel}>
          <CodingChatPanel />
        </div>
      </div>

      {/* 底部：终端面板 */}
      {showTerminal && (
        <div className={styles.bottomPanel} style={{ height: layouts.terminalPanelHeight }}>
          <TerminalPanel
            cwd={projectDir || undefined}
            onClose={() => setShowTerminal(false)}
          />
        </div>
      )}

      {/* 底部：Git 面板 */}
      {showGit && (
        <div className={styles.bottomPanel} style={{ height: layouts.gitPanelHeight }}>
          <GitPanel onFileClick={handleGitFileClick} />
        </div>
      )}
    </div>
  )
}

export default React.memo(CodingPage)
