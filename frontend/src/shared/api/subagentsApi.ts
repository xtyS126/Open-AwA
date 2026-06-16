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
}
