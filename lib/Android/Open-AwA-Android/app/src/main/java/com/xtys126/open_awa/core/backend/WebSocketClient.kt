package com.xtys126.open_awa.core.backend

import android.util.Log
import io.ktor.client.HttpClient
import io.ktor.client.engine.cio.CIO
import io.ktor.client.plugins.websocket.WebSockets
import io.ktor.client.plugins.websocket.webSocket
import io.ktor.client.request.header
import io.ktor.client.request.url
import io.ktor.http.HttpMethod
import io.ktor.websocket.Frame
import io.ktor.websocket.readText
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * WebSocket 事件
 *
 * 通过 [WebSocketClient.events] 暴露给上层，上层按事件类型决定处理逻辑：
 * - [Connected]: 连接建立成功，可清空错误提示
 * - [Message]: 收到文本帧，由上层解析为业务消息
 * - [Disconnected]: 连接正常关闭，不再自动重连
 * - [Reconnecting]: 连接异常，正在第 N 次重连，UI 可提示"重连中"
 * - [Error]: 重连次数耗尽，最终失败
 */
sealed interface WebSocketEvent {
    /** 连接建立成功 */
    data class Connected(val subprotocol: String?) : WebSocketEvent

    /** 收到文本帧 */
    data class Message(val text: String) : WebSocketEvent

    /** 连接正常关闭（服务端主动关闭或本地调用 disconnect） */
    data class Disconnected(val reason: String) : WebSocketEvent

    /** 正在重连，attempt 为第几次重连（从 1 开始），delayMs 为本次退避延迟 */
    data class Reconnecting(val attempt: Int, val delayMs: Long) : WebSocketEvent

    /** 重连耗尽后的最终错误 */
    data class Error(val exception: Throwable) : WebSocketEvent
}

/**
 * WebSocket 连接状态
 *
 * 供 UI 层通过 [WebSocketClient.connectionState] 观察并显示连接指示器。
 */
sealed interface WebSocketConnectionState {
    /** 未连接 */
    object Disconnected : WebSocketConnectionState

    /** 已连接 */
    object Connected : WebSocketConnectionState

    /** 重连中，attempt 为当前重连次数（从 1 开始） */
    data class Reconnecting(val attempt: Int) : WebSocketConnectionState

    /** 最终失败（重连耗尽） */
    data class Failed(val reason: String) : WebSocketConnectionState
}

/**
 * 通用 WebSocket 客户端
 *
 * 基于 Ktor Client WebSocket 插件，提供：
 * 1. 子协议鉴权：通过 Sec-WebSocket-Protocol 头传递 `bearer.<token>`，
 *    避免 token 出现在 URL（泄露到日志/Referer/历史）
 * 2. 自动重连：连接异常时按指数退避重连（1s/2s/4s/8s/16s，封顶 30s），
 *    最多 5 次，超过后进入 [WebSocketConnectionState.Failed]
 * 3. 心跳响应：检测服务端 `{"type":"ping"}` 文本帧，自动回 `{"type":"pong"}`
 * 4. 事件流：通过 [events] 暴露 WebSocket 事件，上层 collect 即可
 * 5. 状态流：通过 [connectionState] 暴露当前连接状态，UI 可观察
 *
 * 使用方式：
 * ```
 * WebSocketClient.connect("ws://host:port/api/chat/ws/session1", "bearer.$token")
 * WebSocketClient.events.collect { event -> ... }
 * WebSocketClient.disconnect()
 * ```
 *
 * 注意：本对象为单例，同一时刻只维护一个 WebSocket 连接。
 * 调用 [connect] 会取消之前的连接并建立新连接。
 */
object WebSocketClient {
    private const val TAG = "WebSocketClient"

    /** 最大重连次数（超过后进入 Failed 状态） */
    private const val MAX_RECONNECT_ATTEMPTS = 5

    /** 重连基础延迟（毫秒），实际延迟 = base * 2^(attempt-1)，封顶 [RECONNECT_MAX_DELAY_MS] */
    private const val RECONNECT_BASE_DELAY_MS = 1000L

    /** 重连最大延迟（毫秒） */
    private const val RECONNECT_MAX_DELAY_MS = 30_000L

    /** 心跳响应 payload */
    private const val PONG_PAYLOAD = """{"type":"pong"}"""

    private val json = Json { ignoreUnknownKeys = true }

    /** 事件流（extraBufferCapacity 避免背压时事件丢失） */
    private val _events = MutableSharedFlow<WebSocketEvent>(extraBufferCapacity = 64)
    val events: SharedFlow<WebSocketEvent> = _events.asSharedFlow()

    /** 连接状态流 */
    private val _connectionState =
        MutableStateFlow<WebSocketConnectionState>(WebSocketConnectionState.Disconnected)
    val connectionState: StateFlow<WebSocketConnectionState> = _connectionState.asStateFlow()

    /** 独立协程作用域，SupervisorJob 保证子协程异常不会互相取消 */
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** 当前连接协程，disconnect 时取消 */
    private var connectJob: Job? = null

    /** 是否应该重连，disconnect 时置 false 终止重连循环 */
    @Volatile
    private var shouldReconnect = false

    /** Ktor HTTP 客户端（懒加载，安装 WebSockets 插件） */
    val client: HttpClient by lazy {
        HttpClient(CIO) {
            install(WebSockets)
        }
    }

    /**
     * 建立 WebSocket 连接
     *
     * 如果当前已有连接，先取消旧连接再建立新连接。
     * 连接异常时自动重连，最多 [MAX_RECONNECT_ATTEMPTS] 次。
     *
     * @param wsUrl WebSocket 完整地址（如 `ws://host:port/api/chat/ws/session1`）
     * @param subprotocol 子协议标识，用于传递鉴权令牌（格式 `bearer.<token>`）
     */
    fun connect(wsUrl: String, subprotocol: String) {
        shouldReconnect = true
        connectJob?.cancel()
        connectJob = scope.launch {
            var attempt = 0
            // 从 ws/wss URL 推导 Origin header（scheme + host + port，不含 path/query）
            // 非浏览器客户端默认不发送 Origin，服务端 validate_ws_origin 会拒绝空 Origin（防 CSWSH）
            // 注意：Origin 规范格式为 scheme://host[:port]，不能包含 path 或 query，
            // 否则会被服务端白名单匹配拒绝
            val origin = buildOriginFromWsUrl(wsUrl)
            while (shouldReconnect) {
                try {
                    client.webSocket(
                        method = HttpMethod.Get,
                        request = {
                            url(wsUrl)
                            header("Sec-WebSocket-Protocol", subprotocol)
                            header("Origin", origin)
                        },
                    ) {
                        // 连接建立成功
                        _connectionState.value = WebSocketConnectionState.Connected
                        _events.emit(WebSocketEvent.Connected(null))
                        Log.d(TAG, "WebSocket 已连接: $wsUrl")

                        // 持续读取 incoming 通道，直到连接关闭或 shouldReconnect=false
                        for (frame in incoming) {
                            if (!shouldReconnect) break
                            if (frame is Frame.Text) {
                                val text = frame.readText()
                                // 心跳响应：检测 ping 自动回 pong
                                if (isPing(text)) {
                                    send(Frame.Text(PONG_PAYLOAD))
                                    continue
                                }
                                _events.emit(WebSocketEvent.Message(text))
                            }
                        }
                    }
                    // webSocket 块正常结束表示连接已关闭
                    if (shouldReconnect) {
                        _connectionState.value = WebSocketConnectionState.Disconnected
                        _events.emit(WebSocketEvent.Disconnected("连接已关闭"))
                        Log.d(TAG, "WebSocket 连接已关闭")
                    }
                    break
                } catch (e: CancellationException) {
                    // 协程被取消（disconnect 调用），正常退出，不重连
                    Log.d(TAG, "WebSocket 连接协程被取消")
                    throw e
                } catch (e: Exception) {
                    Log.w(TAG, "WebSocket 连接异常 (attempt=$attempt): ${e.message}", e)
                    if (!shouldReconnect) break
                    attempt++
                    if (attempt > MAX_RECONNECT_ATTEMPTS) {
                        // 重连耗尽，进入 Failed 状态
                        _connectionState.value = WebSocketConnectionState.Failed(
                            e.message ?: "连接失败",
                        )
                        _events.emit(WebSocketEvent.Error(e))
                        Log.e(TAG, "WebSocket 重连耗尽，最终失败", e)
                        break
                    }
                    // 指数退避：base * 2^(attempt-1)，封顶 maxDelay
                    val delayMs = minOf(
                        RECONNECT_BASE_DELAY_MS * (1L shl (attempt - 1)),
                        RECONNECT_MAX_DELAY_MS,
                    )
                    _connectionState.value = WebSocketConnectionState.Reconnecting(attempt)
                    _events.emit(WebSocketEvent.Reconnecting(attempt, delayMs))
                    Log.d(TAG, "第 $attempt 次重连，延迟 ${delayMs}ms")
                    delay(delayMs)
                }
            }
        }
    }

    /**
     * 断开 WebSocket 连接
     *
     * 取消连接协程并清除状态，不会触发自动重连。
     */
    fun disconnect() {
        shouldReconnect = false
        connectJob?.cancel()
        connectJob = null
        _connectionState.value = WebSocketConnectionState.Disconnected
        Log.d(TAG, "WebSocket 已主动断开")
    }

    /**
     * 判断文本是否为心跳 ping
     *
     * 后端 ws_manager._send_heartbeats 发送 `{"type":"ping"}` 文本帧。
     *
     * @param text 收到的文本帧内容
     * @return true 表示是 ping，需要回 pong
     */
    private fun isPing(text: String): Boolean {
        return try {
            val obj = json.parseToJsonElement(text).jsonObject
            obj["type"]?.jsonPrimitive?.content == "ping"
        } catch (_: Exception) {
            false
        }
    }

    /**
     * 从 ws/wss URL 推导 Origin header
     *
     * Origin 规范格式为 `scheme://host[:port]`，不含 path / query / fragment。
     * 直接把整个 wsUrl 的 scheme 替换会把 path 一起带进 Origin，
     * 导致服务端白名单匹配失败（如 `http://host:port/api/chat/ws/x` 不在白名单）。
     *
     * 协议映射：ws -> http, wss -> https
     *
     * @param wsUrl WebSocket 完整地址（如 `ws://host:port/path`）
     * @return Origin 字符串（如 `http://host:port`）
     */
    private fun buildOriginFromWsUrl(wsUrl: String): String {
        // 1. 协议映射：ws -> http, wss -> https
        val httpUrl = wsUrl
            .replace("ws://", "http://")
            .replace("wss://", "https://")
        // 2. 截断 path / query：保留 scheme://host[:port]
        //    格式：scheme://authority/path?query#fragment
        //    authority 后第一个 / 或 ? 即 path 起点
        val schemeEnd = httpUrl.indexOf("://")
        if (schemeEnd < 0) return httpUrl
        val authorityStart = schemeEnd + 3
        val pathStart = httpUrl.indexOfAny(charArrayOf('/', '?', '#'), authorityStart)
        return if (pathStart >= 0) httpUrl.substring(0, pathStart) else httpUrl
    }
}
