/**
 * MCP API 模块，提供 MCP Server 管理与工具调用的接口方法。
 */
import api from '@/shared/api/api'

/* MCP Server 相关类型 */
export interface MCPServer {
  id: string
  name: string
  transport_type: string
  status: string
  tools_count: number
}

export interface MCPServerCreateData {
  name: string
  command?: string
  args?: string[]
  env?: Record<string, string>
  transport_type: string
  url?: string
}

export interface MCPToolInfo {
  name: string
  description?: string
  inputSchema?: Record<string, unknown>
}

export interface MCPToolCallData {
  server_id: string
  tool_name: string
  arguments?: Record<string, unknown>
}

export interface MCPToolCallResult {
  result: unknown
  is_error: boolean
}

/* MCP API 方法 */
export const mcpAPI = {
  /** 获取 MCP Server 列表 */
  getServers: () => api.get<MCPServer[]>('/mcp/servers'),

  /** 添加 MCP Server */
  addServer: (data: MCPServerCreateData) => api.post<MCPServer>('/mcp/servers', data),

  /** 删除 MCP Server */
  deleteServer: (id: string) => api.delete(`/mcp/servers/${id}`),

  /** 连接 MCP Server */
  connectServer: (id: string) => api.post(`/mcp/servers/${id}/connect`),

  /** 断开 MCP Server */
  disconnectServer: (id: string) => api.post(`/mcp/servers/${id}/disconnect`),

  /** 获取指定 Server 的工具列表 */
  getServerTools: (id: string) => api.get<{ server_id: string; tools: MCPToolInfo[] }>(`/mcp/servers/${id}/tools`),

  /** 调用 MCP 工具 */
  callTool: (data: MCPToolCallData) => api.post<MCPToolCallResult>('/mcp/tools/call', data),
}
