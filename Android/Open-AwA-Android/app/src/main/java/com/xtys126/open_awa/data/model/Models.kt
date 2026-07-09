package com.xtys126.open_awa.data.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 用户实体
 *
 * 对应后端 `/api/auth/me` 接口返回的用户信息
 */
@Serializable
data class User(
    val id: Int,
    val username: String,
    val email: String = "",
    val is_active: Boolean = true,
    val is_admin: Boolean = false,
)

/**
 * 登录请求体
 *
 * 注意：后端 `/api/auth/login` 当前使用 OAuth2PasswordRequestForm 表单提交，
 * 此数据类用于在 Repository 层封装用户名密码，并在调用前转换为表单格式。
 */
@Serializable
data class LoginRequest(
    val username: String,
    val password: String,
)

/**
 * 注册请求体
 */
@Serializable
data class RegisterRequest(
    val username: String,
    val password: String,
    val email: String = "",
)

/**
 * 登录响应（令牌）
 *
 * 对应后端 `/api/auth/login` 返回结构
 */
@Serializable
data class TokenResponse(
    val access_token: String,
    val token_type: String = "bearer",
    /** CSRF 令牌，用于后续写操作的 X-CSRF-Token 请求头 */
    val csrf_token: String? = null,
)

/**
 * 会话实体
 *
 * 对应后端 `/api/chat/sessions` 返回的会话条目
 */
@Serializable
data class Session(
    val id: Int,
    val title: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
)

/**
 * 消息实体
 *
 * 对应后端 `/api/chat/history/{id}` 与 `/api/chat/messages` 返回的消息条目
 */
@Serializable
data class Message(
    val id: Int,
    /** 角色：user / assistant / system */
    val role: String,
    val content: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("session_id") val sessionId: Int,
)

/**
 * 发送消息请求体
 */
@Serializable
data class SendMessageRequest(
    val content: String,
    @SerialName("session_id") val sessionId: Int,
)

/**
 * 创建会话请求体
 */
@Serializable
data class CreateSessionRequest(
    val title: String? = null,
)

/**
 * 流式聊天请求体
 *
 * 对应后端 `POST /api/chat`（mode="stream" 触发 SSE 响应）
 * 字段命名与后端 `ChatMessage` schema 对齐
 */
@Serializable
data class ChatStreamRequest(
    val message: String,
    @SerialName("session_id") val sessionId: String,
    val mode: String = "stream",
    /** 附件列表（base64 内联，对应后端 AttachmentItem；当前未启用，预留字段） */
    val attachments: List<AttachmentItemDto>? = null,
)

/**
 * 附件项（与后端 AttachmentItem 对齐，base64 内联）
 *
 * 当前实现走 `/api/chat/upload` 上传后返回 URL，此结构保留以便后续内联传输
 */
@Serializable
data class AttachmentItemDto(
    val type: String,
    val data: String,
    @SerialName("mime_type") val mimeType: String,
    @SerialName("file_name") val fileName: String? = null,
)

/**
 * 文件上传响应
 *
 * 对应后端 `POST /api/chat/upload` 返回结构
 */
@Serializable
data class AttachmentResponse(
    /** 系统生成的安全文件名（UUID + 扩展名） */
    val filename: String,
    @SerialName("original_name") val originalName: String,
    val size: Long,
    /** 附件分类：image / file */
    val type: String,
    /** 访问 URL（相对路径，如 /api/chat/uploads/xxx.png） */
    val url: String,
)

/**
 * 用户偏好响应
 *
 * 对应后端 `/api/user/preferences` 返回的偏好映射
 */
@Serializable
data class UserPreferences(
    val preferences: Map<String, String?> = emptyMap(),
)

/**
 * 更新用户偏好请求体
 */
@Serializable
data class UpdatePreferencesRequest(
    val preferences: Map<String, String?> = emptyMap(),
)

// ============================================================
// 定时任务相关数据模型
// 对应后端 /api/scheduled-tasks 系列接口
// ============================================================

/**
 * 定时任务实体
 *
 * 对应后端 `GET /api/scheduled-tasks` 与 `POST /api/scheduled-tasks` 返回的任务条目。
 *
 * 字段说明：
 * - [status] 任务状态：pending / running / completed / failed / cancelled
 * - [taskType] 任务类型：ai_prompt（AI 提示词）/ plugin_command（插件命令）
 * - [isDaily] 是否每日重复
 * - [cronExpression] Cron 表达式（与 [isDaily] 互斥，二选一）
 * - [weekdays] 周几执行（逗号分隔的 0-6 数字字符串，0=周日）
 * - [dailyTime] 每日执行时间（HH:MM 格式）
 * - [nextExecutionAt] 下次执行时间（ISO 字符串，后端计算）
 * - [completedAt] 完成时间（仅 status=completed 时有值）
 * - [cancelledAt] 取消时间（仅 status=cancelled 时有值）
 * - [lastErrorMessage] 最近一次错误信息（仅 status=failed 时有值）
 * - [taskMetadata] 任务元数据（如执行结果摘要、自定义参数等）
 */
@Serializable
data class ScheduledTask(
    val id: Int,
    @SerialName("user_id") val userId: String = "",
    val title: String,
    val prompt: String = "",
    @SerialName("scheduled_at") val scheduledAt: String = "",
    val provider: String? = null,
    val model: String? = null,
    @SerialName("is_daily") val isDaily: Boolean = false,
    @SerialName("cron_expression") val cronExpression: String? = null,
    val weekdays: String? = null,
    @SerialName("daily_time") val dailyTime: String? = null,
    @SerialName("task_type") val taskType: String = "ai_prompt",
    @SerialName("plugin_name") val pluginName: String? = null,
    @SerialName("command_name") val commandName: String? = null,
    @SerialName("command_params") val commandParams: Map<String, String> = emptyMap(),
    val status: String = "pending",
    @SerialName("last_error_message") val lastErrorMessage: String? = null,
    @SerialName("task_metadata") val taskMetadata: Map<String, String> = emptyMap(),
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("updated_at") val updatedAt: String = "",
    @SerialName("completed_at") val completedAt: String? = null,
    @SerialName("cancelled_at") val cancelledAt: String? = null,
    @SerialName("next_execution_at") val nextExecutionAt: String? = null,
)

/**
 * 定时任务执行历史实体
 *
 * 对应后端 `GET /api/scheduled-tasks/executions` 返回的执行记录条目。
 *
 * 字段说明：
 * - [status] 执行状态：running / completed / failed
 * - [response] AI 执行结果（status=completed 时有值）
 * - [errorMessage] 执行错误信息（status=failed 时有值）
 * - [executionMetadata] 执行元数据
 */
@Serializable
data class ScheduledTaskExecution(
    val id: Int,
    @SerialName("task_id") val taskId: Int,
    @SerialName("user_id") val userId: String = "",
    @SerialName("task_title") val taskTitle: String = "",
    val prompt: String = "",
    @SerialName("scheduled_for") val scheduledFor: String = "",
    val status: String = "running",
    val response: String? = null,
    @SerialName("error_message") val errorMessage: String? = null,
    val provider: String? = null,
    val model: String? = null,
    @SerialName("request_id") val requestId: String? = null,
    @SerialName("execution_metadata") val executionMetadata: Map<String, String> = emptyMap(),
    @SerialName("started_at") val startedAt: String = "",
    @SerialName("completed_at") val completedAt: String? = null,
)

/**
 * 创建定时任务请求体
 *
 * 对应后端 `POST /api/scheduled-tasks`。
 * 必填字段：[title]、[prompt]、[scheduledAt]（或 [isDaily] + [dailyTime]）
 *
 * @param title 任务标题
 * @param prompt 任务提示词（AI 任务用）
 * @param scheduledAt 首次执行时间（ISO 字符串）
 * @param isDaily 是否每日重复
 * @param cronExpression Cron 表达式（可选）
 * @param weekdays 周几执行（可选）
 * @param dailyTime 每日执行时间（可选）
 * @param taskType 任务类型：ai_prompt / plugin_command
 * @param provider 模型服务提供方（可选）
 * @param model 模型名称（可选）
 */
@Serializable
data class CreateScheduledTaskRequest(
    val title: String,
    val prompt: String,
    @SerialName("scheduled_at") val scheduledAt: String,
    @SerialName("is_daily") val isDaily: Boolean = false,
    @SerialName("cron_expression") val cronExpression: String? = null,
    val weekdays: String? = null,
    @SerialName("daily_time") val dailyTime: String? = null,
    @SerialName("task_type") val taskType: String = "ai_prompt",
    val provider: String? = null,
    val model: String? = null,
    @SerialName("plugin_name") val pluginName: String? = null,
    @SerialName("command_name") val commandName: String? = null,
    @SerialName("command_params") val commandParams: Map<String, String> = emptyMap(),
)

/**
 * 更新定时任务请求体
 *
 * 对应后端 `PUT /api/scheduled-tasks/{id}`，所有字段可选以支持部分更新。
 */
@Serializable
data class UpdateScheduledTaskRequest(
    val title: String? = null,
    val prompt: String? = null,
    @SerialName("scheduled_at") val scheduledAt: String? = null,
    @SerialName("is_daily") val isDaily: Boolean? = null,
    @SerialName("cron_expression") val cronExpression: String? = null,
    val weekdays: String? = null,
    @SerialName("daily_time") val dailyTime: String? = null,
    val status: String? = null,
)
