/**
 * Coding 模式 Zustand 状态管理。
 * 管理打开的文件、编辑器状态、Git 信息和 CC 模式。
 */
import { create } from 'zustand';

export interface OpenFile {
  path: string;
  name: string;
  content: string;
  isDirty: boolean;
  language: string;
}

export interface FileTreeNode {
  name: string;
  type: 'file' | 'directory';
  path: string;
  expanded?: boolean;
  children?: FileTreeNode[];
}

export interface GitChange {
  status: string;
  file: string;
}

interface CodingStore {
  // 文件树
  fileTree: FileTreeNode | null;
  setFileTree: (tree: FileTreeNode | null) => void;
  // 打开的文件
  openFiles: OpenFile[];
  activeFilePath: string | null;
  openFile: (file: OpenFile) => void;
  closeFile: (path: string) => void;
  setActiveFile: (path: string) => void;
  updateFileContent: (path: string, content: string) => void;
  markFileClean: (path: string) => void;
  // Git
  gitChanges: GitChange[];
  gitBranch: string;
  setGitStatus: (branch: string, changes: GitChange[]) => void;
  // CC 模式
  ccModeEnabled: boolean;
  toggleCCMode: () => void;
  // 项目目录
  projectDir: string;
  setProjectDir: (dir: string) => void;
  // Diff
  diffMode: boolean;
  setDiffMode: (mode: boolean) => void;
  // Monaco 编辑器配置
  editorFontSize: number;
  editorTabSize: number;
  editorWordWrap: boolean;
  editorMinimap: boolean;
  setEditorFontSize: (size: number) => void;
}

const getLanguage = (filename: string): string => {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  const langMap: Record<string, string> = {
    ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript',
    py: 'python', rs: 'rust', go: 'go', java: 'java', cpp: 'cpp', c: 'c',
    html: 'html', css: 'css', scss: 'scss', json: 'json', yaml: 'yaml',
    yml: 'yaml', md: 'markdown', sql: 'sql', sh: 'bash', bash: 'bash',
    xml: 'xml', toml: 'toml', ini: 'ini', cfg: 'ini',
  };
  return langMap[ext] || 'plaintext';
};

export const useCodingStore = create<CodingStore>((set, get) => ({
  fileTree: null,
  setFileTree: (tree) => set({ fileTree: tree }),

  openFiles: [],
  activeFilePath: null,

  openFile: (file) => {
    const { openFiles } = get();
    const existing = openFiles.find((f) => f.path === file.path);
    if (existing) {
      set({ activeFilePath: file.path });
      return;
    }
    set({
      openFiles: [...openFiles, { ...file, language: getLanguage(file.name) }],
      activeFilePath: file.path,
    });
  },

  closeFile: (path) => {
    const { openFiles, activeFilePath } = get();
    const newFiles = openFiles.filter((f) => f.path !== path);
    let newActive = activeFilePath;
    if (activeFilePath === path) {
      newActive = newFiles.length > 0 ? newFiles[newFiles.length - 1].path : null;
    }
    set({ openFiles: newFiles, activeFilePath: newActive });
  },

  setActiveFile: (path) => set({ activeFilePath: path }),

  updateFileContent: (path, content) => {
    const { openFiles } = get();
    set({
      openFiles: openFiles.map((f) =>
        f.path === path ? { ...f, content, isDirty: true } : f
      ),
    });
  },

  markFileClean: (path) => {
    const { openFiles } = get();
    set({
      openFiles: openFiles.map((f) =>
        f.path === path ? { ...f, isDirty: false } : f
      ),
    });
  },

  gitChanges: [],
  gitBranch: '',
  setGitStatus: (branch, changes) => set({ gitBranch: branch, gitChanges: changes }),

  ccModeEnabled: false,
  toggleCCMode: () => set((s) => ({ ccModeEnabled: !s.ccModeEnabled })),

  projectDir: '',
  setProjectDir: (dir) => set({ projectDir: dir }),

  diffMode: false,
  setDiffMode: (mode) => set({ diffMode: mode }),

  // Monaco 编辑器配置
  editorFontSize: 14,
  editorTabSize: 2,
  editorWordWrap: false,
  editorMinimap: true,
  setEditorFontSize: (size) => set({ editorFontSize: size }),
}));
