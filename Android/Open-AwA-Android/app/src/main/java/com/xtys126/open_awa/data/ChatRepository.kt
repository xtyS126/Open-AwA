package com.xtys126.open_awa.data

import android.util.Log
import com.xtys126.open_awa.core.backend.ApiClient
import com.xtys126.open_awa.core.backend.ApiException
import com.xtys126.open_awa.data.model.CreateSessionRequest
import com.xtys126.open_awa.data.model.Message
import com.xtys126.open_awa.data.model.SendMessageRequest
import com.xtys126.open_awa.data.model.Session
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json

/**
 * 聊天仓库
 *
 * 封装会话与消息相关接口：
 * 1. 会话列表的增删查
 * 2. 历史消息查询
 * 3. 发送新消息
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

    /** 工具方法：将 JsonElement 安全转换为 JsonObject，非对象时返回 null */
    private val kotlinx.serialization.json.JsonElement.jsonObjectOrNull: kotlinx.serialization.json.JsonObject?
        get() = this as? kotlinx.serialization.json.JsonObject
}
