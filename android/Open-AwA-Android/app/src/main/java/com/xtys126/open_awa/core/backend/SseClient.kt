package com.xtys126.open_awa.core.backend

import android.util.Log
import com.xtys126.open_awa.data.model.ChatStreamRequest
import io.ktor.client.request.header
import io.ktor.client.request.preparePost
import io.ktor.client.request.setBody
import io.ktor.client.statement.bodyAsChannel
import io.ktor.client.statement.bodyAsText
import io.ktor.http.ContentType
import io.ktor.http.contentType
import io.ktor.http.isSuccess
import io.ktor.utils.io.ByteReadChannel
import io.ktor.utils.io.readUTF8Line
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.channelFlow
import kotlinx.coroutines.flow.flowOn
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * SSE 流式聊天客户端
 *
 * 后端 POST /api/chat（mode="stream"）返回 text/event-stream 响应。
 * 由于该端点要求 POST + JSON body，Ktor 自带的 SSE 客户端插件仅支持 GET
 * 请求，因此这里用 preparePost + bodyAsChannel 手动解析 SSE 协议。
 *
 * SSE 事件格式（后端 chat_protocol.build_sse_response 输出）：
 * - data: {"type":"chunk","content":"..."} 正常回复增量文本
 * - event: reasoning + data: {"content":"..."} 推理内容增量
 * - data: {"type":"error","error":{"code":"...","message":"..."}} 错误
 * - data: {"type":"cancelled"} 用户取消
 * - data: [DONE] 流结束
 * - 其他 type（status/plan/task/tool/usage 等）原样透传，由调用方决定是否处理
 *
 * 取消语义：Flow 是冷流，调用方取消 collect 时自动终止读取协程，
 * 底层 HTTP 连接会被关闭，无需显式 cancel。
 */
object SseClient {

    private const val TAG = "SseClient"

    private val json = Json {
        ignoreUnknownKeys = true
        isLenient = true
        encodeDefaults = false
    }

    /**
     * 启动 SSE 流式聊天
     *
     * @param url 完整请求地址（如 http://host:port/api/chat）
     * @param token Authorization Bearer 令牌（可空，未登录时为 null）
     * @param csrf X-CSRF-Token 令牌（可空）
     * @param payload 请求体（包含 message、session_id、mode 等）
     * @return SSE 事件流，调用方 collect 即可按序接收事件
     */
    fun streamChat(
        url: String,
        token: String?,
        csrf: String?,
        payload: ChatStreamRequest,
    ): Flow<SseEvent> = channelFlow {
        try {
            val statement = ApiClient.client.preparePost(url) {
                token?.let { header("Authorization", "Bearer $it") }
                csrf?.let { header("X-CSRF-Token", it) }
                contentType(ContentType.Application.Json)
                setBody(payload)
            }
            statement.execute { response ->
                if (!response.status.isSuccess()) {
                    val errText = try {
                        response.bodyAsText()
                    } catch (_: Throwable) {
                        ""
                    }
                    throw ApiException.HttpError(response.status.value, errText)
                }
                val channel: ByteReadChannel = response.bodyAsChannel()
                val buffer = StringBuilder()
                while (!channel.isClosedForRead) {
                    val line = channel.readUTF8Line() ?: break
                    // 空行表示一个 SSE 事件结束（双换行符 \n\n 之间会有空行）
                    if (line.isEmpty()) {
                        val event = parseEvent(buffer.toString())
                        buffer.setLength(0)
                        if (event != null) {
                            send(event)
                            // 收到 Done 或 Cancelled 后流自然结束，跳出读取循环
                            if (event is SseEvent.Done || event is SseEvent.Cancelled) {
                                return@execute
                            }
                        }
                        continue
                    }
                    buffer.append(line).append('\n')
                }
                // 处理流结束时缓冲区中剩余的最后一个事件
                if (buffer.isNotEmpty()) {
                    val tail = parseEvent(buffer.toString())
                    if (tail != null) send(tail)
                }
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            // 调用方取消 collect 时正常退出，不当作错误
            Log.d(TAG, "SSE 流被取消: ${e.message}")
            throw e
        } catch (e: ApiException) {
            // 已是项目内异常，原样传播
            close(e)
        } catch (e: Throwable) {
            Log.e(TAG, "SSE 连接异常: ${e.message}", e)
            close(ApiException.NetworkError(e.message ?: "SSE 连接失败"))
        }
    }.flowOn(Dispatchers.IO)

    /**
     * 解析单个 SSE 事件块
     *
     * 事件块由多行组成，行格式：
     * - event: <类型>（可选，默认 message）
     * - data: <内容>（可多行，拼接为完整 data）
     * - id: <事件 ID>（忽略）
     * - retry: <毫秒>（忽略）
     *
     * @param raw 事件块原始文本
     * @return 解析后的事件，无法识别的事件返回 null（静默忽略）
     */
    private fun parseEvent(raw: String): SseEvent? {
        val lines = raw.split('\n').map { it.trimEnd() }.filter { it.isNotEmpty() }
        if (lines.isEmpty()) return null

        var eventType = "message"
        val dataLines = mutableListOf<String>()
        for (line in lines) {
            when {
                line.startsWith("event:") -> eventType = line.removePrefix("event:").trim()
                line.startsWith("data:") -> dataLines.add(line.removePrefix("data:").trimStart())
                // 忽略 id / retry / 注释行（: 开头）
            }
        }
        if (dataLines.isEmpty()) return null
        val data = dataLines.joinToString("\n")

        // 流结束信号
        if (data == "[DONE]") {
            return SseEvent.Done
        }

        // 尝试按 JSON 解析
        val jsonObj = try {
            json.parseToJsonElement(data).jsonObject
        } catch (_: Throwable) {
            // 非 JSON data，按 Other 透传
            return SseEvent.Other(eventType, data)
        }

        val type = jsonObj["type"]?.jsonPrimitive?.contentOrNull
        return when (type) {
            "chunk" -> {
                val content = jsonObj["content"]?.jsonPrimitive?.contentOrNull.orEmpty()
                SseEvent.Chunk(content)
            }
            "reasoning" -> {
                val content = jsonObj["content"]?.jsonPrimitive?.contentOrNull.orEmpty()
                SseEvent.Reasoning(content)
            }
            "error" -> {
                val errorObj = jsonObj["error"]?.jsonObject
                val code = errorObj?.get("code")?.jsonPrimitive?.contentOrNull
                    ?: "stream_internal_error"
                val message = errorObj?.get("message")?.jsonPrimitive?.contentOrNull
                    ?: "流式响应异常，请重试"
                SseEvent.Error(code, message)
            }
            "cancelled" -> SseEvent.Cancelled
            else -> SseEvent.Other(type ?: eventType, data)
        }
    }
}

/**
 * SSE 事件类型
 *
 * 调用方根据事件类型决定如何渲染：通常 [Chunk] 拼接到 AI 回复气泡，
 * [Reasoning] 可单独显示为"思考过程"区域，[Error] 抛出或显示错误提示，
 * [Cancelled] 与 [Done] 结束当前一轮流。
 */
sealed class SseEvent {
    /** 正常回复增量文本 */
    data class Chunk(val content: String) : SseEvent()

    /** 推理内容增量（思维链） */
    data class Reasoning(val content: String) : SseEvent()

    /** 错误事件，包含结构化 code 与 message */
    data class Error(val code: String, val message: String) : SseEvent()

    /** 用户取消事件 */
    object Cancelled : SseEvent()

    /** 流结束信号 */
    object Done : SseEvent()

    /** 其他类型事件（status/plan/task/tool/usage 等），原样透传供调用方按需处理 */
    data class Other(val type: String, val data: String) : SseEvent()
}
