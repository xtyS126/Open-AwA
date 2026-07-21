/**
 * 工作流管理 API 模块。
 * 提供工作流定义的 CRUD、执行、执行历史查询等接口。
 */
import api from '@/shared/api/api'

/** 工作流步骤类型 */
export type WorkflowStepType = 'tool' | 'skill' | 'plugin' | 'condition' | 'parallel' | 'sub_workflow'

/** 工作流步骤定义 */
export interface WorkflowStep {
  id: string
  name?: string
  type: WorkflowStepType
  // tool 步骤
  tool?: string
  action?: string
  params?: Record<string, unknown>
  // skill 步骤
  skill_name?: string
  // plugin 步骤
  plugin_name?: string
  plugin_method?: string
  kwargs?: Record<string, unknown>
  // condition 步骤
  expression?: string
  on_true?: WorkflowStep[]
  on_false?: WorkflowStep[]
  // parallel 步骤
  branches?: WorkflowStep[][]
  // sub_workflow 步骤
  workflow_id?: number | null
  workflow_name?: string | null
  inputs?: Record<string, unknown>
  max_depth?: number
  // 通用
  on_error?: 'stop' | 'continue'
}

/** 工作流定义 */
export interface WorkflowDefinition {
  name?: string
  description?: string
  steps: WorkflowStep[]
}

/** 工作流响应 */
export interface WorkflowResponse {
  id: number
  user_id: string
  name: string
  description: string
  format: string
  definition: WorkflowDefinition
  enabled: boolean
  created_at: string
  updated_at: string
}

/** 创建工作流请求 */
export interface WorkflowCreate {
  name: string
  description?: string
  definition: WorkflowDefinition
  format?: string
  enabled?: boolean
}

/** 更新工作流请求 */
export interface WorkflowUpdate {
  name?: string
  description?: string
  definition?: WorkflowDefinition
  format?: string
  enabled?: boolean
}

/** 执行工作流请求 */
export interface WorkflowExecutionRequest {
  input_context?: Record<string, unknown>
}

/** 执行工作流响应 */
export interface WorkflowExecutionResponse {
  status: 'completed' | 'failed'
  workflow_name: string
  steps?: Array<Record<string, unknown>>
  final_context?: Record<string, unknown>
  last_result?: Record<string, unknown>
  error?: string
  execution_id: number | null
}

/** 列出所有工作流 */
export const listWorkflows = async (): Promise<WorkflowResponse[]> => {
  const response = await api.get<WorkflowResponse[]>('/workflows')
  return response.data
}

/** 获取单个工作流 */
export const getWorkflow = async (id: number): Promise<WorkflowResponse> => {
  const response = await api.get<WorkflowResponse>(`/workflows/${id}`)
  return response.data
}

/** 创建工作流 */
export const createWorkflow = async (data: WorkflowCreate): Promise<WorkflowResponse> => {
  const response = await api.post<WorkflowResponse>('/workflows', data)
  return response.data
}

/** 更新工作流 */
export const updateWorkflow = async (id: number, data: WorkflowUpdate): Promise<WorkflowResponse> => {
  const response = await api.put<WorkflowResponse>(`/workflows/${id}`, data)
  return response.data
}

/** 删除工作流 */
export const deleteWorkflow = async (id: number): Promise<void> => {
  await api.delete(`/workflows/${id}`)
}

/** 执行工作流 */
export const executeWorkflow = async (
  id: number,
  inputContext?: Record<string, unknown>
): Promise<WorkflowExecutionResponse> => {
  const response = await api.post<WorkflowExecutionResponse>(
    `/workflows/${id}/execute`,
    { input_context: inputContext || {} }
  )
  return response.data
}
