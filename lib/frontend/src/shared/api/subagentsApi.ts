import api from '@/shared/api/api'

/** 后端注册的子代理信息 */
export interface RegisteredAgent {
  name: string
  description: string
  capabilities: string[]
  registered_at: number
}

/** 执行图节点信息 */
export interface GraphNode {
  name: string
  description: string
  timeout: number
  retry_count: number
}

/** 执行图边信息 */
export interface GraphEdge {
  source: string
  target: string
  conditional: boolean
}

/** 执行图详情 */
export interface GraphDetail {
  name: string
  description: string
  nodes: GraphNode[]
  edges: GraphEdge[]
  entry_point: string | null
  finish_points: string[]
}

/** 图执行结果 */
export interface GraphExecutionResult {
  success: boolean
  results: Record<string, unknown>
  messages: Array<{ role: string; content: string }>
  errors: Record<string, string>
  metadata: Record<string, unknown>
  execution_log: Array<{
    node: string
    status: string
    start_time: number
    end_time: number | null
    duration_ms: number | null
    error: string | null
  }>
}

/** 顺序/并行执行结果 */
export interface AgentExecutionResult {
  success: boolean
  results: Record<string, unknown>
  messages: Array<{ role: string; content: string }>
  errors: Record<string, string>
}

// ── SubagentOrchestrator 类型定义 ──────────────────────────────

/** 隔离级别: 1=上下文 2=进程 3=沙箱 */
export type IsolationLevel = 1 | 2 | 3

/** 结果合并策略 */
export type MergeStrategy = 'concatenate' | 'dag' | 'llm_summary' | 'voting'

/** 子代理生命周期状态 */
export type SubagentLifecycleState =
  | 'created'
  | 'running'
  | 'waiting'
  | 'completed'
  | 'timeout'
  | 'error'
  | 'cancelled'
  | 'terminated'

/** 子代理资源限制 */
export interface ResourceLimits {
  max_turns: number
  max_tokens: number
  max_time_seconds: number
  max_tool_calls: number
  max_output_tokens: number
  soft_timeout_seconds: number
}

/** 子代理任务定义 */
export interface SubagentTaskInput {
  task_id: string
  instruction: string
  context_snippet?: string
  allowed_tools?: string[]
  timeout_seconds?: number
  isolation_level?: IsolationLevel
  resource_limits?: Partial<ResourceLimits>
  metadata?: Record<string, unknown>
}

/** 子代理执行结果 */
export interface SubagentResultOutput {
  task_id: string
  success: boolean
  output: string
  artifacts: unknown[]
  tokens_used: number
  elapsed_seconds: number
  error: string | null
  lifecycle_state: SubagentLifecycleState
  metadata: Record<string, unknown>
}

/** 委派请求 */
export interface DelegateRequest {
  tasks: SubagentTaskInput[]
  merge_strategy?: MergeStrategy
}

/** 委派响应 */
export interface DelegateResponse {
  success: boolean
  results: SubagentResultOutput[]
  merged_output: string
  security_issues: Array<{ task_id: string; issues: string[] }>
  active_tasks: Record<string, SubagentLifecycleState>
}

/** 活跃任务响应 */
export interface ActiveTasksResponse {
  active_tasks: Record<string, SubagentLifecycleState>
  max_parallel: number
}

/** 编排器能力描述 */
export interface OrchestratorCapabilities {
  isolation_levels: Array<{ level: number; name: string; description: string }>
  merge_strategies: Array<{ value: MergeStrategy; description: string }>
  lifecycle_states: SubagentLifecycleState[]
  default_limits: ResourceLimits
}

// ── 图定义持久化类型 ──────────────────────────────────────────

/** 图定义 Schema 节点 */
export interface GraphNodeSchema {
  name: string
  agent: string
  description?: string
}

/** 图定义 Schema 边 */
export interface GraphEdgeSchema {
  source: string
  target: string
  condition?: string
}

/** 图定义 Schema */
export interface GraphDefinitionSchema {
  nodes: GraphNodeSchema[]
  edges: GraphEdgeSchema[]
  entry_point: string
  finish_points: string[]
}

/** 图定义创建请求 */
export interface SubagentDefinitionCreate {
  name: string
  description?: string
  graph_definition: GraphDefinitionSchema
  tags?: string
}

/** 图定义更新请求 */
export interface SubagentDefinitionUpdate {
  name?: string
  description?: string
  graph_definition?: GraphDefinitionSchema
  tags?: string
}

/** 图定义响应 */
export interface SubagentDefinitionResponse {
  id: number
  name: string
  description: string
  graph_definition: GraphDefinitionSchema
  user_id: string
  is_builtin: boolean
  tags: string | null
  created_at: string
  updated_at: string
}

/** 运行图定义请求 */
export interface RunDefinitionRequest {
  context?: Record<string, unknown>
  messages?: Array<{ role: string; content: string }>
}

/** 执行历史响应 */
export interface ExecutionHistoryResponse {
  id: number
  graph_name: string
  user_id: string
  execution_mode: string
  initial_context: Record<string, unknown>
  results: Record<string, unknown>
  errors: Record<string, unknown>
  execution_log: Array<Record<string, unknown>>
  success: boolean
  duration_seconds: number
  created_at: string
}

export const subagentsApi = {
  async listAgents(): Promise<{ agents: RegisteredAgent[]; count: number }> {
    const { data } = await api.get('/subagents/agents')
    return data
  },

  async listGraphs(): Promise<{ graphs: GraphDetail[]; count: number }> {
    const { data } = await api.get('/subagents/graphs')
    return data
  },

  async getGraph(name: string): Promise<GraphDetail> {
    const { data } = await api.get(`/subagents/graphs/${name}`)
    return data
  },

  async runGraph(graphName: string, context?: Record<string, unknown>, messages?: Array<{ role: string; content: string }>): Promise<GraphExecutionResult> {
    const { data } = await api.post('/subagents/run/graph', { graph_name: graphName, context, messages })
    return data
  },

  async runSequential(agentNames: string[], context?: Record<string, unknown>): Promise<AgentExecutionResult> {
    const { data } = await api.post('/subagents/run/sequential', { agent_names: agentNames, context })
    return data
  },

  async runParallel(agentNames: string[], context?: Record<string, unknown>, timeout?: number): Promise<AgentExecutionResult> {
    const { data } = await api.post('/subagents/run/parallel', { agent_names: agentNames, context, timeout })
    return data
  },

  // ── SubagentOrchestrator API ──────────────────────────────

  /** 并行委派多个子代理任务（支持隔离/资源限制/合并策略） */
  async delegate(req: DelegateRequest): Promise<DelegateResponse> {
    const { data } = await api.post('/subagents/orchestrator/delegate', req)
    return data
  },

  /** 取消指定子代理任务 */
  async cancelTask(taskId: string): Promise<{ success: boolean; task_id: string; status: string }> {
    const { data } = await api.post('/subagents/orchestrator/cancel', { task_id: taskId })
    return data
  },

  /** 获取当前活跃的子代理任务列表 */
  async getActiveTasks(): Promise<ActiveTasksResponse> {
    const { data } = await api.get('/subagents/orchestrator/active')
    return data
  },

  /** 获取编排器能力描述（隔离级别/合并策略/默认资源限制） */
  async getCapabilities(): Promise<OrchestratorCapabilities> {
    const { data } = await api.get('/subagents/orchestrator/capabilities')
    return data
  },

  // ── 图定义持久化 API ──────────────────────────────────────

  /** 列出当前用户的图定义（含内置图） */
  async listDefinitions(): Promise<{ definitions: SubagentDefinitionResponse[]; count: number }> {
    const { data } = await api.get('/subagents/definitions')
    // 后端直接返回数组（List[SubagentDefinitionResponse]），前端适配为 { definitions, count }
    const list = Array.isArray(data) ? data : (data?.definitions ?? [])
    return { definitions: list, count: list.length }
  },

  /** 创建图定义 */
  async createDefinition(payload: SubagentDefinitionCreate): Promise<SubagentDefinitionResponse> {
    const { data } = await api.post('/subagents/definitions', payload)
    return data
  },

  /** 更新图定义 */
  async updateDefinition(id: number, payload: SubagentDefinitionUpdate): Promise<SubagentDefinitionResponse> {
    const { data } = await api.put(`/subagents/definitions/${id}`, payload)
    return data
  },

  /** 删除图定义 */
  async deleteDefinition(id: number): Promise<{ success: boolean; id: number }> {
    const { data } = await api.delete(`/subagents/definitions/${id}`)
    return data
  },

  /** 运行图定义 */
  async runDefinition(id: number, payload: RunDefinitionRequest): Promise<GraphExecutionResult> {
    const { data } = await api.post(`/subagents/definitions/${id}/run`, payload)
    return data
  },

  /** 查询执行历史列表（支持按图名称过滤） */
  async listExecutionHistory(graphName?: string): Promise<{ history: ExecutionHistoryResponse[]; count: number }> {
    const params = graphName ? { graph_name: graphName } : {}
    const { data } = await api.get('/subagents/history', { params })
    // 后端直接返回数组（List[ExecutionHistoryResponse]），前端适配为 { history, count }
    const list = Array.isArray(data) ? data : (data?.history ?? [])
    return { history: list, count: list.length }
  },

  /** 获取执行历史详情 */
  async getExecutionHistory(id: number): Promise<ExecutionHistoryResponse> {
    const { data } = await api.get(`/subagents/history/${id}`)
    return data
  },
}
