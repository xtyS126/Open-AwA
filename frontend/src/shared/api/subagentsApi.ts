import api from '@/shared/api/api'

export interface AgentType {
  name: string
  type: string
  description: string
  system_prompt?: string
  tools?: string[]
  disallowed_tools?: string[]
  model?: string
  permission_mode?: string
  memory_mode?: string
  isolation_mode?: string
  background_default?: boolean
}

export const subagentsApi = {
  async listAgents(): Promise<{ agents: AgentType[] }> {
    const { data } = await api.get('/subagents/agents')
    return data
  },

  async listGraphs(): Promise<{ graphs: Array<{ name: string; description: string; node_count: number }> }> {
    const { data } = await api.get('/subagents/graphs')
    return data
  },

  async getGraph(name: string): Promise<{ name: string; nodes: any[]; edges: any[] }> {
    const { data } = await api.get(`/subagents/graphs/${name}`)
    return data
  },

  async runGraph(graphName: string, context?: Record<string, unknown>): Promise<any> {
    const { data } = await api.post('/subagents/run/graph', { graph_name: graphName, context })
    return data
  },

  async runSequential(agents: string[], message: string, context?: Record<string, unknown>): Promise<any> {
    const { data } = await api.post('/subagents/run/sequential', { agents, message, context })
    return data
  },

  async runParallel(agents: string[], message: string, context?: Record<string, unknown>): Promise<any> {
    const { data } = await api.post('/subagents/run/parallel', { agents, message, context })
    return data
  },
}
