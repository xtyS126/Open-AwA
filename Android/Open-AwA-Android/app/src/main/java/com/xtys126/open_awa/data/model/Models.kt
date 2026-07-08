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
