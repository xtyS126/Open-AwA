/**
 * 编辑器面板 — 基于 Monaco Editor 的多标签代码编辑器。
 * 支持语法高亮、自动补全、多标签管理、Ctrl+S 保存。
 */
import React, { useCallback, useRef, useEffect } from 'react'
import Editor, { OnMount } from '@monaco-editor/react'
import type { editor } from 'monaco-editor'
import { useCodingStore } from '../store/codingStore'
import { codingApi } from '../codingApi'
import { useThemeStore } from '@/shared/store/useThemeStore'
import styles from './EditorPane.module.css'

const EditorPane: React.FC = () => {
  const {
    openFiles, activeFilePath, closeFile, setActiveFile,
    updateFileContent, markFileClean, projectDir,
    editorFontSize, editorTabSize, editorWordWrap, editorMinimap,
  } = useCodingStore()
  const { theme } = useThemeStore()

  const activeFile = openFiles.find((f) => f.path === activeFilePath)
  const activeFileRef = useRef(activeFile)
  // 保持 ref 始终指向最新的 activeFile，避免 Monaco 快捷键闭包过期
  useEffect(() => {
    activeFileRef.current = activeFile
  })

  const handleSave = useCallback(async () => {
    const file = activeFileRef.current
    if (!file || !file.isDirty) return
    try {
      await codingApi.writeFile(file.path, file.content, projectDir || undefined)
      markFileClean(file.path)
    } catch (e) {
      console.error('保存失败:', e)
    }
  }, [projectDir, markFileClean])

  const handleEditorMount: OnMount = useCallback((editor) => {
    editorRef.current = editor
    // Ctrl+S 保存 — 通过 ref 读取最新 activeFile，避免闭包过期
    editor.addAction({
      id: 'save-file',
      label: '保存文件',
      keybindings: [2048 | 49], // CtrlCmd + KeyS
      run: () => {
        if (activeFileRef.current?.isDirty) {
          handleSave()
        }
      },
    })
  }, [handleSave])

  const handleContentChange = useCallback((value: string | undefined) => {
    if (activeFile && value !== undefined) {
      updateFileContent(activeFile.path, value)
    }
  }, [activeFile, updateFileContent])

  if (!activeFile) {
    return (
      <div className={styles.empty}>
        <p>选择一个文件开始编辑</p>
      </div>
    )
  }

  const monacoLanguage = activeFile.language && activeFile.language !== 'plaintext'
    ? activeFile.language
    : undefined

  return (
    <div className={styles.editor}>
      <div className={styles.tabs}>
        {openFiles.map((file) => (
          <div
            key={file.path}
            className={`${styles.tab} ${file.path === activeFilePath ? styles.tabActive : ''}`}
            onClick={() => setActiveFile(file.path)}
          >
            <span className={styles.tabName}>
              {file.isDirty && <span className={styles.dirty}>● </span>}
              {file.name}
            </span>
            <button
              className={styles.closeBtn}
              onClick={(e) => { e.stopPropagation(); closeFile(file.path); }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
      <div className={styles.editorBody}>
        <Editor
          height="100%"
          language={monacoLanguage}
          theme={theme === 'dark' ? 'vs-dark' : 'vs'}
          value={activeFile.content}
          onChange={handleContentChange}
          onMount={handleEditorMount}
          options={{
            fontSize: editorFontSize || 14,
            tabSize: editorTabSize || 2,
            wordWrap: editorWordWrap ? 'on' : 'off',
            minimap: { enabled: editorMinimap !== false },
            scrollBeyondLastLine: false,
            automaticLayout: true,
            lineNumbers: 'on',
            renderWhitespace: 'selection',
            bracketPairColorization: { enabled: true },
            padding: { top: 8 },
          }}
        />
      </div>
      <div className={styles.statusBar}>
        <span>{activeFile.language || 'plaintext'}</span>
        <span>{activeFile.content.split('\n').length} 行</span>
        {activeFile.isDirty && <span className={styles.unsaved}>未保存</span>}
      </div>
    </div>
  )
}

export default React.memo(EditorPane)
