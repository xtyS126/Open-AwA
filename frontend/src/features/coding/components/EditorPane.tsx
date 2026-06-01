/**
 * 编辑器面板 — 多标签代码编辑器和内联 Diff 视图。
 */
import React, { useCallback, useEffect, useRef } from 'react';
import { useCodingStore } from '../store/codingStore';
import { codingApi } from '../codingApi';
import styles from './EditorPane.module.css';

const EditorPane: React.FC = () => {
  const {
    openFiles, activeFilePath, closeFile, setActiveFile,
    updateFileContent, markFileClean, projectDir,
  } = useCodingStore();
  const editorRef = useRef<HTMLTextAreaElement>(null);

  const activeFile = openFiles.find((f) => f.path === activeFilePath);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    // Ctrl+S 保存
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      if (activeFile?.isDirty) {
        handleSave();
      }
    }
  }, [activeFile]);

  const handleSave = async () => {
    if (!activeFile) return;
    try {
      await codingApi.writeFile(activeFile.path, activeFile.content, projectDir || undefined);
      markFileClean(activeFile.path);
    } catch (e) {
      console.error('Save failed:', e);
    }
  };

  const handleContentChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    if (activeFile) {
      updateFileContent(activeFile.path, e.target.value);
    }
  };

  if (!activeFile) {
    return (
      <div className={styles.empty}>
        <p>选择一个文件开始编辑</p>
      </div>
    );
  }

  return (
    <div className={styles.editor} onKeyDown={handleKeyDown}>
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
        <div className={styles.lineNumbers}>
          {activeFile.content.split('\n').map((_, i) => (
            <div key={i} className={styles.lineNum}>{i + 1}</div>
          ))}
        </div>
        <textarea
          ref={editorRef}
          className={styles.textArea}
          value={activeFile.content}
          onChange={handleContentChange}
          spellCheck={false}
        />
      </div>
      <div className={styles.statusBar}>
        <span>{activeFile.language || 'plaintext'}</span>
        <span>{activeFile.content.split('\n').length} 行</span>
        {activeFile.isDirty && <span className={styles.unsaved}>未保存</span>}
      </div>
    </div>
  );
};

export default React.memo(EditorPane);
