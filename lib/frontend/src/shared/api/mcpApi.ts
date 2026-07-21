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

/* MCP 资源相关类型 */
export interface MCPResource {
  uri: string
  name: string
  description?: string
  mimeType?: string
}

export interface MCPResourceContent {
  uri: string
  text?: string
  blob?: string
  mimeType?: string
}

/* 指定 Server 的资源列表响应 */
export interface MCPServerResourcesResponse {
  success: boolean
  server_id: string
  resources: MCPResource[]
  count: number
}

/* 资源读取响应 */
export interface MCPResourceReadResponse {
  success: boolean
  server_id: string
  uri: string
  mime_type?: string
  text?: string
  blob?: string
}

/* 全局聚合资源项（包含所属 server_id） */
export interface MCPAggregatedResource extends MCPResource {
  server_id: string
}

/* 全局资源列表响应 */
export interface MCPAllResourcesResponse {
  success: boolean
  resources: MCPAggregatedResource[]
  count: number
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

  /** 获取指定 Server 的资源列表 */
  getServerResources: (serverId: string) =>
    api.get<MCPServerResourcesResponse>(`/mcp/servers/${serverId}/resources`),

  /** 读取指定 Server 的资源内容 */
  readServerResource: (serverId: string, uri: string) =>
    api.post<MCPResourceReadResponse>(`/mcp/servers/${serverId}/resources/read`, { uri }),

  /** 获取所有已连接 Server 的资源列表（聚合） */
  getAllResources: () => api.get<MCPAllResourcesResponse>('/mcp/resources'),
}
