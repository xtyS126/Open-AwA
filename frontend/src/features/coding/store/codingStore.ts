/**
 * Coding 模式 Zustand 状态管理。
 * 管理打开的文件、编辑器状态、Git 信息和 CC 模式。
 */
// [Fix] 消费方使用 shallow equalityFn，改用 createWithEqualityFn 消除 zustand 弃用警告
import { createWithEqualityFn } from 'zustand/traditional';
import { codingApi } from '../codingApi';
import type { WorkbenchProjectId } from '@/features/workbench/workbenchTypes';
import {
  registerWorkbenchProjectSwitchParticipant,
  type WorkbenchPreparedProjectSwitch,
  type WorkbenchProjectSwitchDecision,
} from '@/features/workbench/workbenchProjectSwitchCoordinator';

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

export type CodingMainPanel = 'files' | 'editor' | 'chat';

export interface CodingProjectSnapshot {
  openFiles: OpenFile[];
  activeFilePath: string | null;
  activePanel: CodingMainPanel;
}

export interface CodingRequestContext {
  projectId: WorkbenchProjectId;
  generation: number;
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
  // 工作台项目上下文
  projectId: WorkbenchProjectId | null;
  projectGeneration: number;
  switchingToProjectId: WorkbenchProjectId | null;
  projectSnapshots: Record<string, CodingProjectSnapshot>;
  activePanel: CodingMainPanel;
  setActivePanel: (panel: CodingMainPanel) => void;
  preflightProjectSwitch: (targetProjectId: WorkbenchProjectId) => { dirtyPaths: string[] };
  prepareProjectSwitch: (
    targetProjectId: WorkbenchProjectId,
    decision?: WorkbenchProjectSwitchDecision,
  ) => Promise<WorkbenchPreparedProjectSwitch>;
  syncCommittedProject: (
    projectId: WorkbenchProjectId | null,
    generation: number,
  ) => void;
  captureRequestContext: () => CodingRequestContext | null;
  isRequestContextCurrent: (context: CodingRequestContext) => boolean;
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

function cloneOpenFiles(openFiles: OpenFile[]): OpenFile[] {
  return openFiles.map((file) => ({ ...file }));
}

function createSnapshot(
  state: Pick<CodingStore, 'openFiles' | 'activeFilePath' | 'activePanel'>,
  cleanPaths: ReadonlySet<string> = new Set(),
): CodingProjectSnapshot {
  return {
    openFiles: state.openFiles.map((file) => cleanPaths.has(file.path)
      ? { ...file, isDirty: false }
      : { ...file }),
    activeFilePath: state.activeFilePath,
    activePanel: state.activePanel,
  };
}

async function prepareCodingProjectSwitch(
  targetProjectId: WorkbenchProjectId,
  decision?: WorkbenchProjectSwitchDecision,
): Promise<WorkbenchPreparedProjectSwitch> {
  const before = useCodingStore.getState();
  const sourceProjectId = before.projectId;
  const sourceGeneration = before.projectGeneration;
  const dirtyFiles = before.openFiles.filter((file) => file.isDirty);
  if (dirtyFiles.length > 0 && decision === undefined) {
    throw new Error('当前项目仍有未处理的 dirty 文件');
  }

  const cleanPaths = new Set<string>();
  if (decision === 'save' && sourceProjectId) {
    for (const file of dirtyFiles) {
      await codingApi.writeFile(sourceProjectId, file.path, file.content);
      cleanPaths.add(file.path);
    }
  }

  const latest = useCodingStore.getState();
  if (
    latest.projectId !== sourceProjectId
    || latest.projectGeneration !== sourceGeneration
  ) {
    throw new Error('项目状态已在切换准备期间变化');
  }

  const sourceSnapshot = createSnapshot(latest, cleanPaths);
  const rollbackState = {
    projectId: latest.projectId,
    projectGeneration: latest.projectGeneration,
    switchingToProjectId: null,
    projectSnapshots: latest.projectSnapshots,
    openFiles: cloneOpenFiles(latest.openFiles),
    activeFilePath: latest.activeFilePath,
    activePanel: latest.activePanel,
    fileTree: latest.fileTree,
    gitChanges: latest.gitChanges.map((change) => ({ ...change })),
    gitBranch: latest.gitBranch,
    diffMode: latest.diffMode,
  };
  useCodingStore.setState({ switchingToProjectId: targetProjectId });

  return {
    commit: (generation) => {
      const current = useCodingStore.getState();
      if (
        current.switchingToProjectId !== targetProjectId
        || current.projectId !== sourceProjectId
      ) {
        throw new Error('项目状态已在服务端提交后变化');
      }
      const projectSnapshots = sourceProjectId
        ? { ...current.projectSnapshots, [sourceProjectId]: sourceSnapshot }
        : current.projectSnapshots;
      const targetSnapshot = projectSnapshots[targetProjectId];
      useCodingStore.setState({
        projectId: targetProjectId,
        projectGeneration: generation,
        switchingToProjectId: null,
        projectSnapshots,
        openFiles: targetSnapshot ? cloneOpenFiles(targetSnapshot.openFiles) : [],
        activeFilePath: targetSnapshot?.activeFilePath ?? null,
        activePanel: targetSnapshot?.activePanel ?? 'editor',
        fileTree: null,
        gitChanges: [],
        gitBranch: '',
        diffMode: false,
      });
    },
    abort: () => {
      const current = useCodingStore.getState();
      if (
        current.switchingToProjectId === targetProjectId
        || current.projectId === targetProjectId
      ) {
        useCodingStore.setState(rollbackState);
      }
    },
  };
}

export const useCodingStore = createWithEqualityFn<CodingStore>((set, get) => ({
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

  projectId: null,
  projectGeneration: 0,
  switchingToProjectId: null,
  projectSnapshots: {},
  activePanel: 'editor',
  setActivePanel: (panel) => set({ activePanel: panel }),

  preflightProjectSwitch: (targetProjectId) => {
    const state = get();
    if (state.projectId === targetProjectId) return { dirtyPaths: [] };
    return {
      dirtyPaths: state.openFiles
        .filter((file) => file.isDirty)
        .map((file) => file.path),
    };
  },

  prepareProjectSwitch: (targetProjectId, decision) => (
    prepareCodingProjectSwitch(targetProjectId, decision)
  ),

  syncCommittedProject: (projectId, generation) => {
    const current = get();
    if (current.switchingToProjectId === projectId) {
      set({ projectGeneration: generation });
      return;
    }
    if (current.projectId === projectId) {
      if (current.projectGeneration !== generation) set({ projectGeneration: generation });
      return;
    }
    const projectSnapshots = current.projectId
      ? {
          ...current.projectSnapshots,
          [current.projectId]: createSnapshot(current),
        }
      : current.projectSnapshots;
    const targetSnapshot = projectId ? projectSnapshots[projectId] : undefined;
    set({
      projectId,
      projectGeneration: generation,
      projectSnapshots,
      openFiles: targetSnapshot ? cloneOpenFiles(targetSnapshot.openFiles) : [],
      activeFilePath: targetSnapshot?.activeFilePath ?? null,
      activePanel: targetSnapshot?.activePanel ?? 'editor',
      fileTree: null,
      gitChanges: [],
      gitBranch: '',
      diffMode: false,
    });
  },

  captureRequestContext: () => {
    const state = get();
    return state.projectId
      ? { projectId: state.projectId, generation: state.projectGeneration }
      : null;
  },

  isRequestContextCurrent: (context) => {
    const state = get();
    return state.projectId === context.projectId
      && state.projectGeneration === context.generation;
  },

  diffMode: false,
  setDiffMode: (mode) => set({ diffMode: mode }),

  // Monaco 编辑器配置
  editorFontSize: 14,
  editorTabSize: 2,
  editorWordWrap: false,
  editorMinimap: true,
  setEditorFontSize: (size) => set({ editorFontSize: size }),
}));

registerWorkbenchProjectSwitchParticipant({
  id: 'coding',
  syncCommittedProject: (projectId, generation) => {
    useCodingStore.getState().syncCommittedProject(projectId, generation)
  },
  preflight: ({ fromProjectId, toProjectId }) => {
    const state = useCodingStore.getState();
    if (fromProjectId === toProjectId || state.projectId !== fromProjectId) return [];
    const relativePaths = state.openFiles
      .filter((file) => file.isDirty)
      .map((file) => file.path);
    return relativePaths.length > 0
      ? [{ kind: 'dirty-files', relativePaths }]
      : [];
  },
  prepareSwitch: ({ toProjectId }, decision) => (
    useCodingStore.getState().prepareProjectSwitch(toProjectId, decision)
  ),
});
