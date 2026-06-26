/**
 * 文件树组件 — 显示项目目录结构，支持展开/折叠和文件选择。
 */
import React, { useEffect, useState } from 'react';
import { codingApi, type CodingTreeNode } from '../codingApi';
import { useCodingStore, type FileTreeNode } from '../store/codingStore';
import { appLogger } from '@/shared/utils/logger';
import styles from './FileTree.module.css';

/**
 * 将后端 getTree 返回的嵌套节点（不含 path）映射为前端 FileTreeNode（含 path）。
 * 递归为每个节点拼接相对路径，保证点击文件时能取到正确路径。
 */
function mapTreeNodes(nodes: CodingTreeNode[], parentPath = ''): FileTreeNode[] {
  return nodes.map((node) => {
    const path = parentPath ? `${parentPath}/${node.name}` : node.name;
    return {
      name: node.name,
      type: node.type,
      path,
      expanded: node.expanded,
      children: node.children ? mapTreeNodes(node.children, path) : undefined,
    };
  });
}

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
          setChildren(data.items.map((item) => ({
            name: item.name,
            type: item.type,
            path: item.path,
            expanded: false,
          })));
        }
      } catch (e) {
        // 展开子目录失败时记录警告，避免静默吞异常导致用户无反馈
        appLogger.warning({
          event: 'file_tree_expand_failed',
          module: 'coding',
          message: '展开目录失败',
          extra: { path: node.path, error: e instanceof Error ? e.message : String(e) },
        });
      }
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
          {node.type === 'directory' ? (expanded ? '[DIR-OPEN]' : '[DIR]') : '[FILE]'}
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
  // 使用选择器精确订阅，避免整个 store 变化触发重渲染
  const projectDir = useCodingStore(s => s.projectDir);
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
          children: mapTreeNodes(data.tree, ''),
        });
      }
    } catch (e) {
      appLogger.error({ event: 'file_tree_load_failed', module: 'coding', message: String(e), extra: { stack: e instanceof Error ? e.stack : undefined } });
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
      appLogger.error({ event: 'file_open_failed', module: 'coding', message: String(e), extra: { stack: e instanceof Error ? e.stack : undefined } });
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
