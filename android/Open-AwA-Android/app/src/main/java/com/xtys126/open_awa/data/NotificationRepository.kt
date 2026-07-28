package com.xtys126.open_awa.data

import android.content.Context
import android.util.Log
import com.xtys126.open_awa.core.backend.ApiClient
import com.xtys126.open_awa.core.backend.BackendManager
import com.xtys126.open_awa.core.backend.WebSocketClient
import com.xtys126.open_awa.core.backend.WebSocketConnectionState
import com.xtys126.open_awa.core.backend.WebSocketEvent
import com.xtys126.open_awa.core.notification.SystemNotifier
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.util.UUID

/**
 * 通知类型
 *
 * 对应后端 inbox 消息的 category 字段，以及 WebSocket 推送的消息类型。
 * [value] 与后端 category 字符串保持一致，UI 层按 [value] 匹配图标。
 */
enum class NotificationType(val value: String) {
    /** 普通通知（后端 category=notification） */
    NOTIFICATION("notification"),

    /** 审批通知（后端 category=approval） */
    APPROVAL("approval"),

    /** 任务结果（后端 category=task_result） */
    TASK_RESULT("task_result"),

    /** 聊天消息（WebSocket 推送的 type=message） */
    CHAT("chat"),

    /** 系统通知 */
    SYSTEM("system"),

    /** 计费通知 */
    BILLING("billing"),
}

/**
 * 通知数据模型
 *
 * 后端 inbox 消息结构：`{id, title, content, category, action_url, action_label, read, created_at}`。
 * 其中 `category` 字段通过 [@SerialName] 映射到 [type]，
 * 与 [NotificationType.value] 对齐以便 UI 层按类型匹配图标。
 *
 * WebSocket 推送的聊天消息也包装为 Notification，type 设为 [NotificationType.CHAT.value]。
 */
@Serializable
data class Notification(
    val id: String,
    @SerialName("category") val type: String = NotificationType.NOTIFICATION.value,
    val title: String,
    val content: String,
    @SerialName("created_at") val createdAt: String = "",
    val read: Boolean = false,
)

/**
 * inbox 消息列表响应
 *
 * 对应后端 `GET /api/inbox` 返回结构：
 * `{messages: [...], total: int, unread: int}`
 */
@Serializable
data class InboxListResponse(
    val messages: List<Notification> = emptyList(),
    val total: Int = 0,
    val unread: Int = 0,
)

/**
 * 通知仓库
 *
 * 整合 WebSocket 实时推送与 REST 操作：
 * 1. [start]：建立 WebSocket 连接，接收实时推送
 * 2. [collectEvents]：收集 WebSocket 事件流，解析为 [Notification] 后回调上层，
 *    同时根据 [Notification.type] 触发系统通知栏通知（task_result 走
 *    [SystemNotifier.showTaskResult]，其他走 [SystemNotifier.showGeneric]）
 * 3. [stop]：断开 WebSocket 连接
 * 4. [listMessages]：REST 拉取历史 inbox 消息
 * 5. [markAsRead] / [markAllRead]：REST 标记已读
 *
 * 鉴权：WebSocket token 通过 Sec-WebSocket-Protocol 子协议传递（bearer.<token>），
 * 由 [WebSocketClient.connect] 内部设置，本仓库仅组装 subprotocol 字符串。
 *
 * @param appContext Application 上下文，用于 [SystemNotifier] 显示系统通知。
 *                   可空，为空时仅推送 WebSocket 事件，不显示系统通知（用于无 UI 上下文的场景）。
 */
class NotificationRepository(
    private val appContext: Context? = null,
) {

    private val json = Json { ignoreUnknownKeys = true }

    /** WebSocket 连接状态（委托给 WebSocketClient 单例） */
    val connectionState: StateFlow<WebSocketConnectionState> = WebSocketClient.connectionState

    /**
     * 启动 WebSocket 实时监听
     *
     * 将 HTTP base URL 转为 WebSocket URL，构造 `bearer.<token>` 子协议，
     * 委托 [WebSocketClient.connect] 建立连接。
     *
     * @param accessToken 用户 access_token（从 [AuthRepository.accessTokenFlow] 获取）
     * @param sessionId 会话 ID，用于拼接到 `/api/chat/ws/{session_id}` 路径
     */
    fun start(accessToken: String, sessionId: String) {
        val baseUrl = BackendManager.resolveBaseUrl()
        val wsUrl = baseUrl
            .replace("http://", "ws://")
            .replace("https://", "wss://")
        val wsEndpoint = "$wsUrl/api/chat/ws/$sessionId"
        val subprotocol = "bearer.$accessToken"
        Log.d(TAG, "启动 WebSocket 监听: $wsEndpoint")
        WebSocketClient.connect(wsEndpoint, subprotocol)
    }

    /**
     * 停止 WebSocket 实时监听
     *
     * 断开连接并清除状态，不会触发自动重连。
     */
    fun stop() {
        WebSocketClient.disconnect()
    }

    /**
     * 收集 WebSocket 事件流，解析为 [Notification] 后回调上层
     *
     * 此为挂起函数，内部 `collect` 会阻塞直到协程被取消（页面销毁时）。
     * 调用方应在 `LaunchedEffect` 或 `rememberCoroutineScope` 中调用。
     *
     * 同时根据 [Notification.type] 触发系统通知栏通知：
     * - task_result → [SystemNotifier.showTaskResult]
     * - 其他类型 → [SystemNotifier.showGeneric]
     *
     * 系统通知仅在 [appContext] 非空时触发，避免在无 UI 上下文的场景下显示。
     *
     * @param onEvent 每收到一条可识别的通知时回调，调用方通常将通知插入列表顶部
     */
    suspend fun collectEvents(onEvent: (Notification) -> Unit) {
        WebSocketClient.events.collect { event ->
            if (event is WebSocketEvent.Message) {
                val notification = parseMessageToNotification(event.text)
                if (notification != null) {
                    onEvent(notification)
                    showSystemNotification(notification)
                }
            }
        }
    }

    /**
     * 根据通知类型显示系统通知栏通知
     *
     * @param notification 解析后的通知对象
     */
    private fun showSystemNotification(notification: Notification) {
        val ctx = appContext ?: return
        when (notification.type) {
            NotificationType.TASK_RESULT.value -> {
                SystemNotifier.showTaskResult(
                    context = ctx,
                    title = notification.title,
                    content = notification.content,
                )
            }
            NotificationType.CHAT.value -> {
                // chat 类型的 WebSocket 推送是聊天增量，不显示系统通知
                // 避免聊天界面打开时频繁打扰用户
            }
            else -> {
                SystemNotifier.showGeneric(
                    context = ctx,
                    title = notification.title,
                    content = notification.content,
                    category = notification.type,
                )
            }
        }
    }

    /**
     * 拉取历史 inbox 消息
     *
     * 对应后端 `GET /api/inbox`，返回最近 50 条消息（按 created_at 倒序）。
     *
     * @return inbox 列表响应（含 messages / total / unread）
     * @throws com.xtys126.open_awa.core.backend.ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun listMessages(): InboxListResponse {
        val text = ApiClient.get("inbox")
        return json.decodeFromString(InboxListResponse.serializer(), text)
    }

    /**
     * 拉取未读消息数
     *
     * 对应后端 `GET /api/inbox/count`，返回 `{unread: int, total: int}` 结构。
     * 用于轮询兜底场景：WebSocket 断线时通过此接口同步未读数。
     *
     * @return 未读数（解析失败时返回 0）
     * @throws com.xtys126.open_awa.core.backend.ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun fetchUnreadCount(): Int {
        val text = ApiClient.get("inbox/count")
        return try {
            val obj = json.parseToJsonElement(text).jsonObject
            obj["unread"]?.jsonPrimitive?.contentOrNull?.toIntOrNull() ?: 0
        } catch (e: Exception) {
            Log.w(TAG, "解析未读数失败: ${e.message}", e)
            0
        }
    }

    /**
     * 标记指定消息为已读
     *
     * 对应后端 `POST /api/inbox/{message_id}/read`。
     *
     * @param messageId 消息 ID
     * @throws com.xtys126.open_awa.core.backend.ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun markAsRead(messageId: String) {
        ApiClient.post("inbox/$messageId/read")
    }

    /**
     * 标记全部消息为已读
     *
     * 对应后端 `POST /api/inbox/read-all`。
     *
     * @throws com.xtys126.open_awa.core.backend.ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun markAllRead() {
        ApiClient.post("inbox/read-all")
    }

    /**
     * 解析 WebSocket 文本帧为 [Notification]
     *
     * 支持两种格式：
     * 1. inbox 格式：`{id, title, content, category, created_at, read}` —— 直接映射
     * 2. chat message 格式：`{type:"message", content:"..."}` —— 包装为 CHAT 类型通知
     *
     * 其他格式（ping/pong/status/error 等控制消息）返回 null，不触发 UI 更新。
     *
     * @param text WebSocket 文本帧内容
     * @return 解析成功返回 Notification，无法识别返回 null
     */
    private fun parseMessageToNotification(text: String): Notification? {
        return try {
            val obj = json.parseToJsonElement(text).jsonObject
            // inbox 格式：同时包含 id 和 title 字段
            val id = obj["id"]?.jsonPrimitive?.contentOrNull
            val title = obj["title"]?.jsonPrimitive?.contentOrNull
            if (id != null && title != null) {
                return Notification(
                    id = id,
                    type = obj["category"]?.jsonPrimitive?.contentOrNull
                        ?: NotificationType.NOTIFICATION.value,
                    title = title,
                    content = obj["content"]?.jsonPrimitive?.contentOrNull ?: "",
                    createdAt = obj["created_at"]?.jsonPrimitive?.contentOrNull ?: "",
                    read = obj["read"]?.jsonPrimitive?.booleanOrNull ?: false,
                )
            }
            // chat message 格式：type=message 表示聊天消息增量
            val type = obj["type"]?.jsonPrimitive?.contentOrNull
            if (type == "message") {
                val content = obj["content"]?.jsonPrimitive?.contentOrNull ?: ""
                return Notification(
                    id = UUID.randomUUID().toString().take(12),
                    type = NotificationType.CHAT.value,
                    title = "新消息",
                    content = content,
                    createdAt = "",
                    read = false,
                )
            }
            null
        } catch (e: Exception) {
            Log.w(TAG, "解析 WebSocket 消息失败: ${e.message}", e)
            null
        }
    }

    companion object {
        private const val TAG = "NotificationRepository"
    }
}
