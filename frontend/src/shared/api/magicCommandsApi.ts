import axios from 'axios'

const API_BASE = '/api'

export interface MagicCommand {
  name: string
  description: string
  requires_wait: boolean
  saves_memory: boolean
  clears_context: boolean
  plugin_id: string | null
}

export interface ExecuteCommandResult {
  success: boolean
  command: string
  result: Record<string, unknown>
}

export interface CompactResult {
  success: boolean
  compressed: boolean
  removed_count?: number
  summary?: string
  message?: string
  stats: {
    current_tokens: number
    max_tokens: number
    usage_ratio: number
  }
}

export const magicCommandsApi = {
  async listCommands(): Promise<{ commands: MagicCommand[]; total: number }> {
    const res = await axios.get(`${API_BASE}/magic-commands`)
    return res.data
  },

  async executeCommand(commandName: string, context?: Record<string, unknown>): Promise<ExecuteCommandResult> {
    const res = await axios.post(`${API_BASE}/magic-commands/execute`, {
      command_name: commandName,
      context: context || {},
    })
    return res.data
  },

  async compact(sessionId: string, workspaceId?: string, modelName?: string): Promise<CompactResult> {
    const res = await axios.post(`${API_BASE}/magic-commands/compact`, {
      session_id: sessionId,
      workspace_id: workspaceId || 'default',
      model_name: modelName || 'default',
    })
    return res.data
  },
}
