/**
 * Coding 模式 API 模块。
 * 类型与 backend/api/routes/coding.py 及 core/coding/* 服务的实际响应结构对齐。
 */
import api from '@/shared/api/api';
import type { WorkbenchProjectId } from '@/features/workbench/workbenchTypes';

/** 文件树节点类型。 */
export type CodingFileType = 'file' | 'directory';

/** getTree 返回的节点（backend _build_tree 不含 path 字段）。 */
export interface CodingTreeNode {
  name: string;
  type: CodingFileType;
  expanded?: boolean;
  children?: CodingTreeNode[];
}

/** getTree 接口返回结构。 */
export interface CodingTreeResponse {
  root: string;
  tree: CodingTreeNode[];
}

/** listDir 返回的节点项（backend list_directory 包含 path 字段）。 */
export interface CodingListDirItem {
  name: string;
  path: string;
  type: CodingFileType;
  size?: number;
}

/** listDir 接口返回结构。 */
export interface CodingListDirResponse {
  path?: string;
  items: CodingListDirItem[];
  count?: number;
  error?: string;
}

/** readFile 接口返回结构。 */
export interface CodingReadFileResponse {
  path: string;
  content: string;
  size: number;
  lines: number;
}

/** writeFile 接口返回结构。 */
export interface CodingWriteFileResponse {
  path: string;
  written: boolean;
  size: number;
}

/** searchFiles 命中项。 */
export interface CodingSearchFilesItem {
  name: string;
  path: string;
  size: number;
}

/** searchFiles 接口返回结构。 */
export interface CodingSearchFilesResponse {
  results: CodingSearchFilesItem[];
  count: number;
}

/** Git 文件状态变更行。 */
export interface GitStatusChange {
  status: string;
  file: string;
}

/** gitStatus 接口返回结构（仓库存在时）。 */
export interface CodingGitStatusOkResponse {
  branch: string;
  changes: GitStatusChange[];
  changed_count: number;
  is_clean: boolean;
  is_repo: true;
}

/** gitStatus 接口返回结构（非仓库时）。 */
export interface CodingGitStatusNoRepoResponse {
  error: string;
  is_repo: false;
}

export type CodingGitStatusResponse = CodingGitStatusOkResponse | CodingGitStatusNoRepoResponse;

/** gitDiff 接口返回结构。 */
export interface CodingGitDiffResponse {
  diff: string;
  file: string;
  error?: string;
}

/** Git 提交记录条目。 */
export interface GitLogItem {
  hash: string;
  message: string;
  author: string;
  date: string;
}

/** gitLog 接口返回结构。 */
export interface CodingGitLogResponse {
  commits: GitLogItem[];
  count: number;
  error?: string;
}

/** gitCommit 接口返回结构。 */
export interface CodingGitCommitResponse {
  message: string;
  output?: string;
  error?: string;
}

/** Git 分支项。 */
export interface GitBranchItem {
  name: string;
  current: boolean;
}

/** gitBranches 接口返回结构。 */
export interface CodingGitBranchesResponse {
  branches: GitBranchItem[];
  error?: string;
}

/** AST 定义/引用搜索命中项。 */
export interface AstDefinitionHit {
  name: string;
  type?: string;
  context?: string;
  file: string;
  line: number;
  col: number;
}

/** AST 模式搜索命中项。 */
export interface AstPatternHit {
  file: string;
  line: number;
  match: string;
}

/** AST 定义/引用搜索响应。 */
export interface CodingAstDefinitionSearchResponse {
  results: AstDefinitionHit[];
  count: number;
}

/** AST 模式搜索响应。 */
export interface CodingAstPatternSearchResponse {
  results: AstPatternHit[];
  count: number;
}

/** AST 文件结构概览。 */
export interface CodingAstStructureResponse {
  imports?: Array<{ name: string; alias?: string | null }>;
  classes?: Array<Record<string, unknown>>;
  functions?: Array<Record<string, unknown>>;
  top_level?: Array<Record<string, unknown>>;
  symbols?: Array<Record<string, unknown>>;
  error?: string;
}

/** Diff 计算响应（与 backend DiffEngine.compute_inline_diff 一致）。 */
export interface CodingDiffResponse {
  diff?: string;
  [key: string]: unknown;
}

/** LSP 诊断条目（目前后端固定返回空数组，预留结构）。 */
export interface LspDiagnostic {
  line: number;
  column: number;
  severity: string;
  message: string;
  source?: string;
}

/** LSP 诊断响应。 */
export interface CodingLspDiagnosticsResponse {
  success: boolean;
  language?: string;
  lsp_available?: boolean;
  diagnostics: LspDiagnostic[];
  message?: string;
  error?: string;
}

/** LSP 补全响应。 */
export interface CodingLspCompletionsResponse {
  success: boolean;
  completions: Array<Record<string, unknown>>;
  file_path?: string;
  error?: string;
}

/** LSP hover 响应。 */
export interface CodingLspHoverResponse {
  success: boolean;
  hover: string;
  file_path?: string;
  error?: string;
}

/** LSP 符号响应。 */
export interface CodingLspSymbolsResponse {
  success: boolean;
  symbols: Array<Record<string, unknown>>;
  error?: string;
}

/** Claude Code 模式切换响应。 */
export interface CodingToggleCCModeResponse {
  success: boolean;
  cc_mode_enabled: boolean;
}

export const codingApi = {
  // ---- 文件树 ----
  /** 获取目录树结构（嵌套格式）。 */
  getTree: async (projectId: WorkbenchProjectId, path = ''): Promise<CodingTreeResponse> => {
    const { data } = await api.get<CodingTreeResponse>('/coding/tree', { params: { path, project_id: projectId } });
    return data;
  },
  /** 列出目录内容（扁平结构，含相对路径）。 */
  listDir: async (projectId: WorkbenchProjectId, path = ''): Promise<CodingListDirResponse> => {
    const { data } = await api.get<CodingListDirResponse>('/coding/list', { params: { path, project_id: projectId } });
    return data;
  },
  /** 读取文件内容。 */
  readFile: async (projectId: WorkbenchProjectId, path: string): Promise<CodingReadFileResponse> => {
    const { data } = await api.post<CodingReadFileResponse>('/coding/read', { path, project_id: projectId });
    return data;
  },
  /** 写入文件内容。 */
  writeFile: async (projectId: WorkbenchProjectId, path: string, content: string): Promise<CodingWriteFileResponse> => {
    const { data } = await api.post<CodingWriteFileResponse>('/coding/write', { path, content, project_id: projectId });
    return data;
  },
  /** 按文件名模式搜索文件。 */
  searchFiles: async (projectId: WorkbenchProjectId, pattern: string, directory = ''): Promise<CodingSearchFilesResponse> => {
    const { data } = await api.post<CodingSearchFilesResponse>('/coding/search-files', { pattern, directory, project_id: projectId });
    return data;
  },

  // ---- Git ----
  /** 获取 Git 工作区状态。 */
  gitStatus: async (projectId: WorkbenchProjectId): Promise<CodingGitStatusResponse> => {
    const { data } = await api.get<CodingGitStatusResponse>('/coding/git/status', { params: { project_id: projectId } });
    return data;
  },
  /** 获取 Git 差异（统一 diff 文本）。 */
  gitDiff: async (projectId: WorkbenchProjectId, filePath?: string, staged = false): Promise<CodingGitDiffResponse> => {
    const { data } = await api.get<CodingGitDiffResponse>('/coding/git/diff', { params: { file_path: filePath, staged, project_id: projectId } });
    return data;
  },
  /** 获取 Git 提交历史。 */
  gitLog: async (projectId: WorkbenchProjectId, maxCount = 20): Promise<CodingGitLogResponse> => {
    const { data } = await api.get<CodingGitLogResponse>('/coding/git/log', { params: { max_count: maxCount, project_id: projectId } });
    return data;
  },
  /** 提交变更。 */
  gitCommit: async (projectId: WorkbenchProjectId, message: string, files?: string[]): Promise<CodingGitCommitResponse> => {
    const { data } = await api.post<CodingGitCommitResponse>('/coding/git/commit', { message, files, project_id: projectId });
    return data;
  },
  /** 获取分支列表。 */
  gitBranches: async (projectId: WorkbenchProjectId): Promise<CodingGitBranchesResponse> => {
    const { data } = await api.get<CodingGitBranchesResponse>('/coding/git/branches', { params: { project_id: projectId } });
    return data;
  },

  // ---- AST 搜索 ----
  /** 按符号名搜索定义。 */
  searchDefinitions: async (projectId: WorkbenchProjectId, name: string): Promise<CodingAstDefinitionSearchResponse> => {
    const { data } = await api.get<CodingAstDefinitionSearchResponse>('/coding/ast/definitions', { params: { name, project_id: projectId } });
    return data;
  },
  /** 按符号名搜索引用。 */
  searchReferences: async (projectId: WorkbenchProjectId, name: string): Promise<CodingAstDefinitionSearchResponse> => {
    const { data } = await api.get<CodingAstDefinitionSearchResponse>('/coding/ast/references', { params: { name, project_id: projectId } });
    return data;
  },
  /** 按 AST 模式搜索。 */
  searchPattern: async (projectId: WorkbenchProjectId, pattern: string): Promise<CodingAstPatternSearchResponse> => {
    const { data } = await api.post<CodingAstPatternSearchResponse>('/coding/ast/search', { pattern, project_id: projectId });
    return data;
  },
  /** 获取文件结构概览。 */
  getStructure: async (projectId: WorkbenchProjectId, filePath: string): Promise<CodingAstStructureResponse> => {
    const { data } = await api.get<CodingAstStructureResponse>('/coding/ast/structure', { params: { file_path: filePath, project_id: projectId } });
    return data;
  },

  // ---- Diff ----
  /** 计算两段文本的差异。 */
  computeDiff: async (original: string, modified: string): Promise<CodingDiffResponse> => {
    const { data } = await api.post<CodingDiffResponse>('/coding/diff', { original, modified });
    return data;
  },

  // ---- LSP ----
  /** 获取 LSP 诊断信息。 */
  getLSPDiagnostics: async (projectId: WorkbenchProjectId, filePath: string): Promise<CodingLspDiagnosticsResponse> => {
    const { data } = await api.get<CodingLspDiagnosticsResponse>('/coding/lsp/diagnostics', { params: { file_path: filePath, project_id: projectId } });
    return data;
  },
  /** 获取 LSP 补全建议。 */
  getLSPCompletions: async (projectId: WorkbenchProjectId, filePath: string, line: number, column: number): Promise<CodingLspCompletionsResponse> => {
    const { data } = await api.post<CodingLspCompletionsResponse>('/coding/lsp/completions', { file_path: filePath, line, column, project_id: projectId });
    return data;
  },
  /** 获取 LSP hover 信息。 */
  getLSPHover: async (projectId: WorkbenchProjectId, filePath: string, line: number, column: number): Promise<CodingLspHoverResponse> => {
    const { data } = await api.post<CodingLspHoverResponse>('/coding/lsp/hover', { file_path: filePath, line, column, project_id: projectId });
    return data;
  },
  /** 获取文件符号列表。 */
  getLSPSymbols: async (projectId: WorkbenchProjectId, filePath: string): Promise<CodingLspSymbolsResponse> => {
    const { data } = await api.get<CodingLspSymbolsResponse>('/coding/lsp/symbols', { params: { file_path: filePath, project_id: projectId } });
    return data;
  },

  // ---- Claude Code 模式 ----
  /** 切换 Claude Code 模式开关。 */
  toggleCCMode: async (enabled: boolean): Promise<CodingToggleCCModeResponse> => {
    const { data } = await api.post<CodingToggleCCModeResponse>('/coding/cc-mode', { enabled });
    return data;
  },
};
