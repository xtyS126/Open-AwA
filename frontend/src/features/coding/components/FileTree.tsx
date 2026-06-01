/**
 * 文件树组件 — 显示项目目录结构，支持展开/折叠和文件选择。
 */
import React, { useEffect, useState } from 'react';
import { codingApi } from '../codingApi';
import { useCodingStore, type FileTreeNode } from '../store/codingStore';
import styles from './FileTree.module.css';

const FileTreeItem: React.FC<{
  node: FileTreeNode;
  depth: number;
  onSelectFile: (path: string) => void;
}> = ({ node, depth, onSelectFile }) => {
  const [expanded, setExpanded] = useState(node.expanded ?? depth < 2);
  const [children, setChildren] = useState<FileTreeNode[]>(node.children || []);

  const handleToggle = async () => {
    if (node.type === 'file') {
      onSelectFile(node.path);
      return;
    }
    if (!expanded && children.length === 0) {
      try {
        const data = await codingApi.listDir(node.path);
        if (data.items) {
          setChildren(data.items.map((item: any) => ({
            name: item.name,
            type: item.type,
            path: item.path,
            expanded: false,
          })));
        }
      } catch (e) { /* ignore */ }
    }
    setExpanded(!expanded);
  };

  return (
    <div className={styles.item}>
      <div
        className={`${styles.row} ${node.type === 'file' ? styles.file : styles.dir}`}
        style={{ paddingLeft: depth * 16 + 8 }}
        onClick={handleToggle}
      >
        <span className={styles.icon}>
          {node.type === 'directory' ? (expanded ? '📂' : '📁') : '📄'}
        </span>
        <span className={styles.name}>{node.name}</span>
      </div>
      {node.type === 'directory' && expanded && children.map((child) => (
        <FileTreeItem
          key={child.path}
          node={child}
          depth={depth + 1}
          onSelectFile={onSelectFile}
        />
      ))}
    </div>
  );
};

const FileTree: React.FC = () => {
  const { projectDir } = useCodingStore();
  const [rootTree, setRootTree] = useState<FileTreeNode | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadTree();
  }, [projectDir]);

  const loadTree = async () => {
    try {
      setLoading(true);
      const data = await codingApi.getTree('', projectDir || undefined);
      if (data && data.tree) {
        setRootTree({
          name: data.root || 'Project',
          type: 'directory',
          path: '',
          expanded: true,
          children: data.tree,
        });
      }
    } catch (e) {
      console.error('Failed to load file tree:', e);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectFile = async (path: string) => {
    try {
      const data = await codingApi.readFile(path, projectDir || undefined);
      if (data.content !== undefined) {
        const store = useCodingStore.getState();
        store.openFile({
          path,
          name: path.split('/').pop() || path,
          content: data.content,
          isDirty: false,
          language: '',
        });
      }
    } catch (e) {
      console.error('Failed to open file:', e);
    }
  };

  if (loading) return <div className={styles.loading}>加载文件树...</div>;

  return (
    <div className={styles.tree}>
      <div className={styles.header}>
        文件
        <button className={styles.refreshBtn} onClick={loadTree} title="刷新">↻</button>
      </div>
      {rootTree && (
        <FileTreeItem node={rootTree} depth={0} onSelectFile={handleSelectFile} />
      )}
    </div>
  );
};

export default React.memo(FileTree);
