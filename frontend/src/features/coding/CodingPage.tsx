/**
 * Coding 模式主页面 — 三面板 IDE 布局。
 * 左侧：文件树 | 中间：编辑器/Diff 视图 | 右侧：Coding 聊天助手
 * 底部：Git 面板
 */
import React, { useEffect, useState, useCallback } from 'react'
import { shallow } from 'zustand/shallow'
import FileTree from './components/FileTree'
import EditorPane from './components/EditorPane'
import DiffView from './components/DiffView'
import GitPanel from './components/GitPanel'
import CodingChatPanel from './components/CodingChatPanel'
import ModeSwitcher, { type ExecutionMode } from './components/ModeSwitcher'
import { useCodingStore } from './store/codingStore'
import { codingApi } from './codingApi'
import { useWorkbenchProjectStore } from '@/features/workbench/store/workbenchProjectStore'
import { asWorkbenchProjectId } from '@/features/workbench/workbenchTypes'
import { appLogger } from '@/shared/utils/logger'
import { useBreakpoint } from '@/shared/hooks/useBreakpoint'
import ErrorBoundary from '@/shared/components/ErrorBoundary/ErrorBoundary'
import styles from './CodingPage.module.css'

// 搜索结果项（来自 AST 搜索接口，兼容定义搜索与模式搜索两种命中结构）
interface SearchResultItem {
  file: string
  line: number
  name?: string
  type?: string
  match?: string
  context?: string
  col?: number
}

// 移动端主面板 Tab 标识：文件树 / 编辑器 / 聊天
const CodingPage: React.FC = () => {
  // 使用选择器 + shallow 浅比较，避免整个 store 变化触发重渲染
  const {
    projectId, ccModeEnabled, toggleCCMode,
    diffMode, setDiffMode, openFiles, activeFilePath,
    mobileMainPanel, setMobileMainPanel,
  } = useCodingStore(s => ({
    projectId: s.projectId,
    ccModeEnabled: s.ccModeEnabled,
    toggleCCMode: s.toggleCCMode,
    diffMode: s.diffMode,
    setDiffMode: s.setDiffMode,
    openFiles: s.openFiles,
    activeFilePath: s.activeFilePath,
    mobileMainPanel: s.activePanel,
    setMobileMainPanel: s.setActivePanel,
  }), shallow)
  const {
    projects,
    currentProjectId,
    switchGeneration,
    workbenchPhase,
    selectProject,
  } = useWorkbenchProjectStore(s => ({
    projects: s.projects,
    currentProjectId: s.currentProjectId,
    switchGeneration: s.switchGeneration,
    workbenchPhase: s.phase,
    selectProject: s.selectProject,
  }), shallow)
  const [showGit, setShowGit] = useState(false)
  const [executionMode, setExecutionMode] = useState<ExecutionMode>('solo')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResultItem[]>([])
  const [diffData, setDiffData] = useState<{ original: string; modified: string; filePath: string } | null>(null)
  const [layouts] = useState({
    fileTreeWidth: 240,
    gitPanelHeight: 180,
  })
  // 移动端主面板 Tab 切换：默认展示编辑器（最常用）
  const { isMobile } = useBreakpoint()

  // 仅在服务端工作台上下文提交后同步 Coding 项目状态。
  useEffect(() => {
    useCodingStore.getState().syncCommittedProject(currentProjectId, switchGeneration)
    setSearchResults([])
    setDiffData(null)
  }, [currentProjectId, switchGeneration])

  const handleProjectChange = useCallback((value: string) => {
    if (!value || value === projectId) return
    void selectProject(asWorkbenchProjectId(value)).catch(() => undefined)
  }, [projectId, selectProject])

  useEffect(() => {
    codingApi.toggleCCMode(ccModeEnabled).catch((error) => {
      appLogger.error({ event: 'cc_mode_sync_failed', module: 'coding', message: 'CC模式同步失败', extra: { error: error instanceof Error ? error.message : String(error) } })
    })
  }, [ccModeEnabled])

  const handleSearch = useCallback(async () => {
    const request = useCodingStore.getState().captureRequestContext()
    if (!projectId || !searchQuery.trim() || !request) return
    try {
      const defs = await codingApi.searchDefinitions(request.projectId, searchQuery)
      if (!useCodingStore.getState().isRequestContextCurrent(request)) return
      if (defs.results?.length > 0) {
        setSearchResults(defs.results)
        return
      }
      const pattern = await codingApi.searchPattern(request.projectId, searchQuery)
      if (!useCodingStore.getState().isRequestContextCurrent(request)) return
      setSearchResults(pattern.results || [])
    } catch (e) {
      appLogger.error({ event: 'search_failed', module: 'coding', message: String(e), extra: e instanceof Error ? { stack: e.stack } : undefined })
    }
  }, [searchQuery, projectId])

  const handleResultClick = async (result: SearchResultItem) => {
    if (result.file) {
      const request = useCodingStore.getState().captureRequestContext()
      if (!request) return
      try {
        const data = await codingApi.readFile(request.projectId, result.file)
        if (data.content !== undefined && useCodingStore.getState().isRequestContextCurrent(request)) {
          useCodingStore.getState().openFile({
            path: result.file,
            name: result.file.split('/').pop() || result.file,
            content: data.content,
            isDirty: false,
            language: '',
          })
        }
      } catch (e) {
        appLogger.error({ event: 'search_result_open_failed', module: 'coding', message: String(e), extra: { file: result.file, stack: e instanceof Error ? e.stack : undefined } })
      }
    }
  }

  // Git 文件点击查看 diff
  const handleGitFileClick = useCallback(async (filePath: string) => {
    const request = useCodingStore.getState().captureRequestContext()
    if (!projectId || !request) return
    try {
      const diffResult = await codingApi.gitDiff(request.projectId, filePath, false)
      if (!useCodingStore.getState().isRequestContextCurrent(request)) return
      const activeFile = openFiles.find((f) => f.path === filePath)
      const currentContent = activeFile?.content || ''
      // 后端 gitDiff 仅返回统一 diff 文本（diffResult.diff），不返回原始文件内容。
      // TODO: 后端补充 git show HEAD:<file> 接口以获取原始内容，使 DiffView 能展示真正的差异。
      // 当前回退到当前内容，DiffView 暂不展示差异（保持原有行为）。
      void diffResult  // 标记已消费响应，等待后端补全 original 字段
      const originalContent = currentContent

      setDiffData({
        original: originalContent,
        modified: currentContent,
        filePath,
      })
      setDiffMode(true)
    } catch (e) {
      appLogger.error({ event: 'diff_fetch_failed', module: 'coding', message: String(e), extra: e instanceof Error ? { stack: e.stack } : undefined })
    }
  }, [projectId, openFiles, setDiffMode])

  const handleAcceptDiff = useCallback(async () => {
    setDiffMode(false)
    setDiffData(null)
  }, [setDiffMode])

  const handleRejectDiff = useCallback(() => {
    setDiffMode(false)
    setDiffData(null)
  }, [setDiffMode])

  const activeFile = openFiles.find((f) => f.path === activeFilePath)
  const projectSelector = (
    <select
      aria-label="切换 Coding 项目"
      value={projectId ?? ''}
      disabled={workbenchPhase === 'loading' || workbenchPhase === 'switching'}
      onChange={(event) => void handleProjectChange(event.target.value)}
    >
      <option value="">选择项目</option>
      {projects.map((project) => (
        <option key={project.id} value={project.id} disabled={!project.isEnabled}>
          {project.displayName}
        </option>
      ))}
    </select>
  )
  // ===== 移动端布局：单栏 + 顶部 Tab 切换（文件 / 编辑器 / 聊天） =====
  if (isMobile) {
    return (
      <div className={styles.container}>
        {/* 工具栏 —— 移动端紧凑化 */}
        <div className={styles.toolbar}>
          <div className={styles.toolbarLeft}>
            {projectSelector}
            <button
              className={`${styles.gitToggle} ${showGit ? styles.gitActive : ''}`}
              onClick={() => setShowGit(!showGit)}
            >
              Git
            </button>
            <button
              className={`${styles.ccToggle} ${ccModeEnabled ? styles.ccActive : ''}`}
              onClick={toggleCCMode}
              title={ccModeEnabled ? 'Claude Code 模式已启用' : '启用 Claude Code 模式'}
            >
              {ccModeEnabled ? 'CC ON' : 'CC OFF'}
            </button>
          </div>
          <div className={styles.toolbarCenter}>
            <input
              type="text"
              className={styles.searchInput}
              placeholder="搜索..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
        </div>

        {/* 主面板 Tab 切换条 */}
        <div className={styles.mobileTabBar} role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={mobileMainPanel === 'files'}
            onClick={() => setMobileMainPanel('files')}
            className={`${styles.mobileTab} ${mobileMainPanel === 'files' ? styles.active : ''}`}
          >
            文件
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mobileMainPanel === 'editor'}
            onClick={() => setMobileMainPanel('editor')}
            className={`${styles.mobileTab} ${mobileMainPanel === 'editor' ? styles.active : ''}`}
          >
            编辑器
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mobileMainPanel === 'chat'}
            onClick={() => setMobileMainPanel('chat')}
            className={`${styles.mobileTab} ${mobileMainPanel === 'chat' ? styles.active : ''}`}
          >
            聊天
          </button>
        </div>

        {/* 主面板：根据 Tab 显示对应面板 */}
        <div className={styles.mobileMainPanel}>
          {mobileMainPanel === 'files' && (
            <ErrorBoundary name="FileTree">
              <FileTree />
            </ErrorBoundary>
          )}
          {mobileMainPanel === 'editor' && (
            <ErrorBoundary name="EditorPane">
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
            </ErrorBoundary>
          )}
          {mobileMainPanel === 'chat' && (
            <ErrorBoundary name="CodingChatPanel">
              <CodingChatPanel />
            </ErrorBoundary>
          )}

          {/* 搜索结果覆盖层 —— 仅在编辑器 Tab 显示 */}
          {mobileMainPanel === 'editor' && searchResults.length > 0 && (
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

        {/* 底部：终端面板（受工具栏按钮控制） */}
        {/* 底部：Git 面板（受工具栏按钮控制） */}
        {showGit && (
          <div className={styles.bottomPanel} style={{ height: layouts.gitPanelHeight }}>
            <ErrorBoundary name="GitPanel">
              <GitPanel onFileClick={handleGitFileClick} />
            </ErrorBoundary>
          </div>
        )}
      </div>
    )
  }

  // ===== 桌面端布局：原三栏 + 底部可选面板 =====
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
            {projects.find((project) => project.id === projectId)?.displayName ?? '未选择项目'}
          </span>
          {projectSelector}
        </div>
      </div>

      {/* 主面板 */}
      <div className={styles.mainPanel}>
        {/* 左侧：文件树 */}
        <div className={styles.leftPanel} style={{ width: layouts.fileTreeWidth }}>
          <ErrorBoundary name="FileTree">
            <FileTree />
          </ErrorBoundary>
        </div>

        {/* 中间：编辑器或 Diff 视图 */}
        <div className={styles.centerPanel}>
          <ErrorBoundary name="EditorPane">
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
          </ErrorBoundary>
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
          <ErrorBoundary name="CodingChatPanel">
            <CodingChatPanel />
          </ErrorBoundary>
        </div>
      </div>

      {/* 底部：终端面板 */}
      {/* 底部：Git 面板 */}
      {showGit && (
        <div className={styles.bottomPanel} style={{ height: layouts.gitPanelHeight }}>
          <ErrorBoundary name="GitPanel">
            <GitPanel onFileClick={handleGitFileClick} />
          </ErrorBoundary>
        </div>
      )}
    </div>
  )
}

export default React.memo(CodingPage)
