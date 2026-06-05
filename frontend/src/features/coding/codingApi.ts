/**
 * Coding 模式 API 模块。
 */
import api from '@/shared/api/api';

export const codingApi = {
  // 文件树
  getTree: async (path = '', projectDir?: string) => {
    const { data } = await api.get('/coding/tree', { params: { path, project_dir: projectDir } });
    return data;
  },
  listDir: async (path = '', projectDir?: string) => {
    const { data } = await api.get('/coding/list', { params: { path, project_dir: projectDir } });
    return data;
  },
  readFile: async (path: string, projectDir?: string) => {
    const { data } = await api.post('/coding/read', { path, project_dir: projectDir });
    return data;
  },
  writeFile: async (path: string, content: string, projectDir?: string) => {
    const { data } = await api.post('/coding/write', { path, content, project_dir: projectDir });
    return data;
  },
  searchFiles: async (pattern: string, directory = '', projectDir?: string) => {
    const { data } = await api.post('/coding/search-files', { pattern, directory, project_dir: projectDir });
    return data;
  },

  // Git
  gitStatus: async (projectDir?: string) => {
    const { data } = await api.get('/coding/git/status', { params: { project_dir: projectDir } });
    return data;
  },
  gitDiff: async (filePath?: string, staged = false, projectDir?: string) => {
    const { data } = await api.get('/coding/git/diff', { params: { file_path: filePath, staged, project_dir: projectDir } });
    return data;
  },
  gitLog: async (maxCount = 20, projectDir?: string) => {
    const { data } = await api.get('/coding/git/log', { params: { max_count: maxCount, project_dir: projectDir } });
    return data;
  },
  gitCommit: async (message: string, files?: string[], projectDir?: string) => {
    const { data } = await api.post('/coding/git/commit', { message, files, project_dir: projectDir });
    return data;
  },
  gitBranches: async (projectDir?: string) => {
    const { data } = await api.get('/coding/git/branches', { params: { project_dir: projectDir } });
    return data;
  },

  // AST 搜索
  searchDefinitions: async (name: string, projectDir?: string) => {
    const { data } = await api.get('/coding/ast/definitions', { params: { name, project_dir: projectDir } });
    return data;
  },
  searchReferences: async (name: string, projectDir?: string) => {
    const { data } = await api.get('/coding/ast/references', { params: { name, project_dir: projectDir } });
    return data;
  },
  searchPattern: async (pattern: string, projectDir?: string) => {
    const { data } = await api.post('/coding/ast/search', { pattern, project_dir: projectDir });
    return data;
  },
  getStructure: async (filePath: string, projectDir?: string) => {
    const { data } = await api.get('/coding/ast/structure', { params: { file_path: filePath, project_dir: projectDir } });
    return data;
  },

  // Diff
  computeDiff: async (original: string, modified: string) => {
    const { data } = await api.post('/coding/diff', { original, modified });
    return data;
  },

  // LSP
  getLSPDiagnostics: async (filePath: string, projectDir?: string) => {
    const { data } = await api.get('/coding/lsp/diagnostics', { params: { file_path: filePath, project_dir: projectDir } });
    return data;
  },
  getLSPCompletions: async (filePath: string, line: number, column: number, projectDir?: string) => {
    const { data } = await api.post('/coding/lsp/completions', { file_path: filePath, line, column, project_dir: projectDir });
    return data;
  },
  getLSPHover: async (filePath: string, line: number, column: number, projectDir?: string) => {
    const { data } = await api.post('/coding/lsp/hover', { file_path: filePath, line, column, project_dir: projectDir });
    return data;
  },
  getLSPSymbols: async (filePath: string, projectDir?: string) => {
    const { data } = await api.get('/coding/lsp/symbols', { params: { file_path: filePath, project_dir: projectDir } });
    return data;
  },

  // Claude Code 模式
  toggleCCMode: async (enabled: boolean) => {
    const { data } = await api.post('/coding/cc-mode', { enabled });
    return data;
  },
};
