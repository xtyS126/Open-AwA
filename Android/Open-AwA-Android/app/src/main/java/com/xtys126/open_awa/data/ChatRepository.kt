package com.xtys126.open_awa.data

import android.util.Log
import com.xtys126.open_awa.core.backend.ApiClient
import com.xtys126.open_awa.core.backend.ApiException
import com.xtys126.open_awa.core.backend.BackendManager
import com.xtys126.open_awa.core.backend.SseClient
import com.xtys126.open_awa.core.backend.SseEvent
import com.xtys126.open_awa.data.model.AttachmentResponse
import com.xtys126.open_awa.data.model.ChatStreamRequest
import com.xtys126.open_awa.data.model.CreateSessionRequest
import com.xtys126.open_awa.data.model.Message
import com.xtys126.open_awa.data.model.SendMessageRequest
import com.xtys126.open_awa.data.model.Session
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.mapNotNull
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import java.io.File

/**
 * 聊天仓库
 *
 * 封装会话与消息相关接口：
 * 1. 会话列表的增删查
 * 2. 历史消息查询
 * 3. 发送新消息（普通 / SSE 流式）
 * 4. 聊天附件上传
 *
 * 所有接口通过 [ApiClient] 调用后端 `/api/chat/` 下的聊天接口
 */
class ChatRepository {

    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        encodeDefaults = false
    }

    companion object {
        private const val TAG = "ChatRepository"

        /** 无效 sessionId 占位符，前端可能传入字符串 "undefined" / "null" */
        private val INVALID_SESSION_IDS = setOf("undefined", "null", "")
    }

    /**
     * 获取会话列表
     *
     * @return 当前用户的会话列表，按更新时间倒序
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun getSessions(): List<Session> {
        val responseText = ApiClient.get("chat/sessions")
        // 后端可能返回裸数组或 { items: [...] } 结构，先尝试裸数组
        return runCatching {
            json.decodeFromString(ListSerializer(Session.serializer()), responseText)
        }.getOrElse {
            // 兼容 { items: [...] } 结构
            val element = json.parseToJsonElement(responseText)
            val items = element.jsonObjectOrNull?.get("items")
                ?: element.jsonObjectOrNull?.get("sessions")
                ?: element.jsonObjectOrNull?.get("data")
            if (items != null) {
                json.decodeFromString(ListSerializer(Session.serializer()), items.toString())
            } else {
                throw ApiException.HttpError(200, "无法解析会话列表: $responseText")
            }
        }
    }

    /**
     * 创建会话
     *
     * @param title 会话标题，为空时由后端生成默认标题
     * @return 新建的会话对象
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun createSession(title: String? = null): Session {
        val request = CreateSessionRequest(title = title)
        val responseText = ApiClient.post("chat/sessions", request)
        return json.decodeFromString(Session.serializer(), responseText)
    }

    /**
     * 删除会话
     *
     * @param id 会话 ID
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun deleteSession(id: Int) {
        ApiClient.delete("chat/sessions/$id")
    }

    /**
     * 获取会话历史消息
     *
     * @param sessionId 会话 ID
     * @return 历史消息列表，按时间正序
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun getHistory(sessionId: String): List<Message> {
        // 容错：sessionId 为 "undefined"/"null"/空字符串时直接返回空列表
        if (sessionId.isBlank() || sessionId.lowercase() in INVALID_SESSION_IDS) {
            Log.d(TAG, "getHistory: sessionId 无效，返回空列表: $sessionId")
            return emptyList()
        }
        val responseText = ApiClient.get("chat/history/$sessionId")
        return runCatching {
            json.decodeFromString(ListSerializer(Message.serializer()), responseText)
        }.getOrElse {
            // 兼容 { messages: [...] } 结构
            val element = json.parseToJsonElement(responseText)
            val items = element.jsonObjectOrNull?.get("messages")
                ?: element.jsonObjectOrNull?.get("items")
                ?: element.jsonObjectOrNull?.get("data")
            if (items != null) {
                json.decodeFromString(ListSerializer(Message.serializer()), items.toString())
            } else {
                emptyList()
            }
        }
    }

    /**
     * 发送消息
     *
     * @param sessionId 会话 ID
     * @param content 消息内容
     * @return 助手回复消息（或后端返回的最新消息）
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun sendMessage(sessionId: Int, content: String): Message {
        val request = SendMessageRequest(content = content, sessionId = sessionId)
        val responseText = ApiClient.post("chat/messages", request)
        return json.decodeFromString(Message.serializer(), responseText)
    }

    /**
     * 流式发送消息（SSE）
     *
     * 调用后端 `POST /api/chat`（mode="stream"），返回 AI 回复增量文本流。
     * 调用方 collect Flow 即可实时拿到每一段文本，取消 collect 自动终止 SSE 连接。
     *
     * 事件过滤规则：
     * - [SseEvent.Chunk]：正常回复增量，yield content
     * - [SseEvent.Reasoning]：推理内容增量，当前不在主流中返回（后续可在 UI 单独展示）
     * - [SseEvent.Error]：转换为 [ApiException.HttpError] 抛出，触发调用方 catch
     * - [SseEvent.Cancelled] / [SseEvent.Done]：结束流，不返回内容
     * - [SseEvent.Other]：透传事件（status/plan/task/tool/usage 等），当前不返回
     *
     * @param sessionId 会话 ID（字符串形式，与后端 ChatMessage.session_id 对齐）
     * @param content 用户消息内容
     * @return AI 回复增量文本流
     */
    fun streamMessage(sessionId: String, content: String): Flow<String> {
        val payload = ChatStreamRequest(
            message = content,
            sessionId = sessionId,
            mode = "stream",
        )
        val url = "${BackendManager.resolveBaseUrl()}/api/chat"
        return SseClient.streamChat(
            url = url,
            token = ApiClient.getAccessToken(),
            csrf = ApiClient.getCsrfToken(),
            payload = payload,
        ).mapNotNull { event ->
            when (event) {
                is SseEvent.Chunk -> event.content
                is SseEvent.Error -> throw ApiException.HttpError(
                    500,
                    "[${event.code}] ${event.message}",
                )
                is SseEvent.Reasoning -> null
                is SseEvent.Cancelled -> null
                is SseEvent.Done -> null
                is SseEvent.Other -> null
            }
        }
    }

    /**
     * 上传聊天附件
     *
     * 调用后端 `POST /api/chat/upload`（multipart/form-data，字段名 `file`）。
     * 后端校验扩展名白名单与 magic bytes，返回安全文件名与访问 URL。
     *
     * @param filePath 本地文件绝对路径
     * @param mimeType MIME 类型（如 "image/png"），需与文件内容匹配
     * @return 上传响应（包含 filename / original_name / size / type / url）
     * @throws ApiException 文件不存在、网络或 HTTP 错误时抛出
     */
    suspend fun uploadAttachment(filePath: String, mimeType: String): AttachmentResponse {
        val file = File(filePath)
        if (!file.exists()) {
            Log.e(TAG, "上传文件不存在: $filePath")
            throw ApiException.NetworkError("文件不存在: $filePath")
        }
        val bytes = file.readBytes()
        val responseText = ApiClient.uploadFile(
            path = "chat/upload",
            bytes = bytes,
            fileName = file.name,
            mimeType = mimeType,
        )
        return json.decodeFromString(AttachmentResponse.serializer(), responseText)
    }

    /**
     * 上传聊天附件（字节数组版本，适配 Android Uri 选择器）
     *
     * Android 文件选择器（ActivityResultContracts.GetContent）返回的是 Uri
     * 而非文件路径，调用方需自行通过 ContentResolver 读取字节，再用此方法上传。
     *
     * @param bytes 文件二进制内容
     * @param fileName 原始文件名（含扩展名，后端据此校验类型）
     * @param mimeType MIME 类型（如 "image/png"）
     * @return 上传响应
     * @throws ApiException 网络或 HTTP 错误时抛出
     */
    suspend fun uploadAttachmentBytes(
        bytes: ByteArray,
        fileName: String,
        mimeType: String,
    ): AttachmentResponse {
        val responseText = ApiClient.uploadFile(
            path = "chat/upload",
            bytes = bytes,
            fileName = fileName,
            mimeType = mimeType,
        )
        return json.decodeFromString(AttachmentResponse.serializer(), responseText)
    }

    /** 工具方法：将 JsonElement 安全转换为 JsonObject，非对象时返回 null */
    private val kotlinx.serialization.json.JsonElement.jsonObjectOrNull: kotlinx.serialization.json.JsonObject?
        get() = this as? kotlinx.serialization.json.JsonObject
}
