/**
 * 定时任务 API 模块。封装 AI 提示/插件命令类定时任务管理端点。自 api.ts 拆分而来。
 */
import { api } from './client'
import type { ScheduledTaskType } from './types'

export interface ScheduledTask {
  id: number
  user_id: string
  title: string
  prompt: string
  scheduled_at: string
  status: string
  provider: string | null
  model: string | null
  is_daily?: boolean | null
  cron_expression?: string | null
  weekdays?: string | null
  daily_time?: string | null
  task_type?: ScheduledTaskType | string | null
  plugin_name?: string | null
  command_name?: string | null
  command_params?: Record<string, unknown>
  last_error_message: string | null
  task_metadata: Record<string, unknown>
  created_at: string
  updated_at: string
  completed_at: string | null
  cancelled_at: string | null
  next_execution_at?: string | null
}

export interface ScheduledTaskExecution {
  id: number
  task_id: number
  user_id: string
  task_title: string
  prompt: string
  scheduled_for: string
  status: string
  response: string | null
  error_message: string | null
  provider: string | null
  model: string | null
  request_id: string | null
  execution_metadata: Record<string, unknown>
  started_at: string
  completed_at: string | null
}

export interface ScheduledTaskCreatePayload {
  title: string
  prompt: string
  scheduled_at: string
  provider?: string | null
  model?: string | null
  is_daily?: boolean | null
  cron_expression?: string | null
  weekdays?: string | null
  daily_time?: string | null
  task_type?: ScheduledTaskType | string
  plugin_name?: string | null
  command_name?: string | null
  command_params?: Record<string, unknown>
}

export interface ScheduledTaskUpdatePayload {
  title?: string
  prompt?: string
  scheduled_at?: string
  provider?: string | null
  model?: string | null
  is_daily?: boolean | null
  cron_expression?: string | null
  weekdays?: string | null
  daily_time?: string | null
  task_type?: ScheduledTaskType | string
  plugin_name?: string | null
  command_name?: string | null
  command_params?: Record<string, unknown>
}

export interface PluginCommandInfo {
  plugin_name: string
  plugin_version: string
  plugin_description: string
  command_name: string
  command_description: string
  command_method: string
  parameters: Record<string, unknown>
}

export const scheduledTasksAPI = {
  getAll: (params?: { status?: string; limit?: number }) =>
    api.get<ScheduledTask[]>('/scheduled-tasks', { params }),
  getOne: (id: number) =>
    api.get<ScheduledTask>(`/scheduled-tasks/${id}`),
  create: (payload: ScheduledTaskCreatePayload) =>
    api.post<ScheduledTask>('/scheduled-tasks', payload),
  update: (id: number, payload: ScheduledTaskUpdatePayload) =>
    api.put<ScheduledTask>(`/scheduled-tasks/${id}`, payload),
  cancel: (id: number) =>
    api.delete<{ message: string }>(`/scheduled-tasks/${id}`),
  getExecutions: (params?: { task_id?: number; limit?: number }) =>
    api.get<ScheduledTaskExecution[]>('/scheduled-tasks/executions', { params }),
  getPluginCommands: () =>
    api.get<PluginCommandInfo[]>('/scheduled-tasks/plugin-commands'),
}
