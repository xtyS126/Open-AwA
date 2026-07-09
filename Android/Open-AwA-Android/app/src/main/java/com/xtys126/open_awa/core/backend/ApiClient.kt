package com.xtys126.open_awa.core.backend

import android.util.Log
import io.ktor.client.HttpClient
import io.ktor.client.engine.cio.CIO
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.plugins.logging.LogLevel
import io.ktor.client.plugins.logging.Logging
import io.ktor.client.request.forms.FormDataContent
import io.ktor.client.request.forms.MultiPartFormDataContent
import io.ktor.client.request.forms.formData
import io.ktor.client.request.header
import io.ktor.client.request.post
import io.ktor.client.request.preparePost
import io.ktor.client.request.request
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsText
import io.ktor.client.statement.bodyAsChannel
import io.ktor.http.ContentType
import io.ktor.http.Headers
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.contentType
import io.ktor.http.isSuccess
import io.ktor.http.parametersOf
import io.ktor.serialization.kotlinx.json.json
import io.ktor.utils.io.readUTF8Line
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.serialization.json.Json

/**
 * API 客户端
 *
 * 封装 Ktor HTTP 客户端，统一处理：
 * 1. BaseUrl 解析（[BackendManager.resolveBaseUrl]）
 * 2. JSON 序列化/反序列化
 * 3. CSRF 令牌/Authorization 令牌注入
 * 4. 错误处理
 * 5. SSE 流式响应解析（[streamSSE]）
 *
 * 所有 API 调用通过 [ApiClient] 单例进行
 */
object ApiClient {
    private const val TAG = "ApiClient"

    /** CSRF 令牌（登录后从 cookie 或响应头获取） */
    @Volatile
    private var csrfToken: String? = null

    /** Authorization 令牌（登录后获取） */
    @Volatile
    private var accessToken: String? = null

    /** Ktor HTTP 客户端（懒加载，[streamSSE] 通过 [HttpResponse.bodyAsChannel] 流式读取 SSE） */
    val client: HttpClient by lazy {
        HttpClient(CIO) {
            install(ContentNegotiation) {
                json(Json {
                    ignoreUnknownKeys = true
                    isLenient = true
                    encodeDefaults = false
                })
            }
            install(Logging) {
                level = LogLevel.NONE // 生产环境关闭日志，调试时改为 HEADERS
            }
        }
    }

    /**
     * 设置访问令牌
     */
    fun setAccessToken(token: String?) {
        accessToken = token
    }

    /**
     * 获取访问令牌（供 SseClient 等模块复用同一份令牌）
     */
    fun getAccessToken(): String? = accessToken

    /**
     * 设置 CSRF 令牌
     */
    fun setCsrfToken(token: String?) {
        csrfToken = token
    }

    /**
     * 获取 CSRF 令牌（供 SseClient 等模块复用同一份令牌）
     */
    fun getCsrfToken(): String? = csrfToken

    /**
     * 发起 HTTP 请求
     *
     * @param path API 路径（不含 /api 前缀，如 "auth/login"）
     * @param method HTTP 方法
     * @param body 请求体（可空）
     * @return 响应字符串，失败抛 [ApiException]
     */
    suspend fun request(
        path: String,
        method: HttpMethod = HttpMethod.Get,
        body: Any? = null,
    ): String {
        val baseUrl = BackendManager.resolveBaseUrl()
        val url = "$baseUrl/api/$path"
        Log.d(TAG, "请求: $method $url")

        val response = try {
            client.request(url) {
                this.method = method
                // 注入 Authorization
                accessToken?.let { header("Authorization", "Bearer $it") }
                // 注入 CSRF
                csrfToken?.let { header("X-CSRF-Token", it) }
                // 注入请求体
                if (body != null) {
                    setBody(body)
                    header("Content-Type", "application/json")
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "请求失败: ${e.message}", e)
            throw ApiException.NetworkError(e.message ?: "网络错误")
        }

        val text = response.bodyAsText()
        if (!response.status.isSuccess()) {
            Log.e(TAG, "HTTP ${response.status.value}: $text")
            throw ApiException.HttpError(response.status.value, text)
        }
        return text
    }

    /**
     * GET 请求
     */
    suspend fun get(path: String): String = request(path, HttpMethod.Get)

    /**
     * POST 请求
     */
    suspend fun post(path: String, body: Any? = null): String =
        request(path, HttpMethod.Post, body)

    /**
     * POST application/x-www-form-urlencoded 请求
     *
     * 用于后端 OAuth2PasswordRequestForm 接口（如 /api/auth/login）。
     *
     * @param path API 路径（不含 /api 前缀）
     * @param form 表单键值对
     * @return 响应字符串，失败抛 [ApiException]
     */
    suspend fun postForm(path: String, form: Map<String, String>): String {
        val baseUrl = BackendManager.resolveBaseUrl()
        val url = "$baseUrl/api/$path"
        Log.d(TAG, "表单请求: POST $url")

        val response = try {
            client.post(url) {
                accessToken?.let { header("Authorization", "Bearer $it") }
                csrfToken?.let { header("X-CSRF-Token", it) }
                setBody(
                    FormDataContent(
                        parametersOf(form.mapValues { listOf(it.value) }),
                    ),
                )
            }
        } catch (e: Exception) {
            Log.e(TAG, "表单请求失败: ${e.message}", e)
            throw ApiException.NetworkError(e.message ?: "网络错误")
        }

        val text = response.bodyAsText()
        if (!response.status.isSuccess()) {
            Log.e(TAG, "表单请求 HTTP ${response.status.value}: $text")
            throw ApiException.HttpError(response.status.value, text)
        }
        return text
    }

    /**
     * PUT 请求
     */
    suspend fun put(path: String, body: Any? = null): String =
        request(path, HttpMethod.Put, body)

    /**
     * DELETE 请求
     */
    suspend fun delete(path: String): String = request(path, HttpMethod.Delete)

    /**
     * 发起 SSE 流式请求
     *
     * 用于 ACP vibe coding 的 POST /api/acp/sessions/{id}/prompt 端点，
     * 后端返回 text/event-stream 格式的事件流。
     *
     * 实现方式：由于 Ktor 2.x 的 client SSE 插件在 Maven Central 不存在
     * （ktor-client-sse 是 Ktor 3.x 才有的 artifact），这里用 preparePost +
     * bodyAsChannel 手动解析 SSE 协议帧，与 [SseClient] 的解析逻辑一致。
     *
     * SSE 帧格式（标准 W3C EventSource 规范）：
     * - `event: <类型>` 指定事件类型（可空，默认 message）
     * - `data: <内容>` 数据行（可多行，拼接为完整 data）
     * - 空行表示一帧结束
     *
     * 鉴权头（Authorization / X-CSRF-Token）在此处统一注入。
     *
     * 错误处理：
     * 1. 网络异常（连接失败/超时）→ 抛 [ApiException.NetworkError]
     * 2. HTTP 4xx/5xx → 抛 [ApiException.HttpError]
     * 3. 调用方取消 collect → 协程取消，底层 HTTP 连接自动关闭
     *
     * @param path API 路径（不含 /api 前缀，如 "acp/sessions/xxx/prompt"）
     * @param requestJson 请求体 JSON 字符串（POST body），为 null 时不发送请求体
     * @return SSE 事件流，每个元素为 (事件类型, 数据 JSON 字符串)
     */
    fun streamSSE(path: String, requestJson: String? = null): Flow<Pair<String, String>> = flow {
        val baseUrl = BackendManager.resolveBaseUrl()
        val url = "$baseUrl/api/$path"
        Log.d(TAG, "SSE 请求: POST $url")

        try {
            val statement = client.preparePost(url) {
                accessToken?.let { header("Authorization", "Bearer $it") }
                csrfToken?.let { header("X-CSRF-Token", it) }
                contentType(ContentType.Application.Json)
                if (requestJson != null) {
                    setBody(requestJson)
                }
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
                val channel = response.bodyAsChannel()
                val buffer = StringBuilder()
                while (!channel.isClosedForRead) {
                    val line = channel.readUTF8Line() ?: break
                    // 空行表示一个 SSE 事件结束
                    if (line.isEmpty()) {
                        val event = parseSseFrame(buffer.toString())
                        buffer.setLength(0)
                        if (event != null) {
                            emit(event)
                        }
                        continue
                    }
                    buffer.append(line).append('\n')
                }
                // 处理流结束时缓冲区中剩余的最后一帧
                if (buffer.isNotEmpty()) {
                    val tail = parseSseFrame(buffer.toString())
                    if (tail != null) emit(tail)
                }
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            // 调用方取消 collect，正常退出
            Log.d(TAG, "SSE 流被取消: ${e.message}")
            throw e
        } catch (e: ApiException) {
            // 已是项目内异常，原样传播
            throw e
        } catch (e: Exception) {
            Log.e(TAG, "SSE 流式请求失败: ${e.message}", e)
            throw ApiException.NetworkError(e.message ?: "SSE 流式请求失败")
        }
    }

    /**
     * 解析单个 SSE 事件帧
     *
     * @param raw 帧原始文本（多行）
     * @return (事件类型, 数据) 二元组，无法识别返回 null
     */
    private fun parseSseFrame(raw: String): Pair<String, String>? {
        val lines = raw.split('\n').map { it.trimEnd() }.filter { it.isNotEmpty() }
        if (lines.isEmpty()) return null

        var eventType = "message"
        val dataLines = mutableListOf<String>()
        for (line in lines) {
            when {
                line.startsWith("event:") -> eventType = line.removePrefix("event:").trim()
                line.startsWith("data:") -> dataLines.add(line.removePrefix("data:").trimStart())
                // 忽略 id / retry / 注释行
            }
        }
        if (dataLines.isEmpty()) return null
        return eventType to dataLines.joinToString("\n")
    }

    /**
     * 上传文件（multipart/form-data）
     *
     * 对应后端 `POST /api/chat/upload`：
     * - 表单字段 `file`：文件二进制
     * - 鉴权：与普通请求一致，注入 Authorization + X-CSRF-Token 头
     * - 大小限制：10MB（后端校验）
     * - 允许扩展名：.jpg/.jpeg/.png/.gif/.webp/.pdf/.txt/.md/.csv
     *
     * @param path API 路径（不含 /api 前缀，如 "chat/upload"）
     * @param bytes 文件二进制内容
     * @param fileName 原始文件名（含扩展名，后端据此校验类型）
     * @param mimeType MIME 类型（如 "image/png"）
     * @param extraFields 额外表单字段（可空）
     * @return 响应字符串（JSON），失败抛 [ApiException]
     */
    suspend fun uploadFile(
        path: String,
        bytes: ByteArray,
        fileName: String,
        mimeType: String,
        extraFields: Map<String, String> = emptyMap(),
    ): String {
        val baseUrl = BackendManager.resolveBaseUrl()
        val url = "$baseUrl/api/$path"
        Log.d(TAG, "上传文件: POST $url (fileName=$fileName, mimeType=$mimeType, size=${bytes.size})")

        val response = try {
            client.post(url) {
                accessToken?.let { header("Authorization", "Bearer $it") }
                csrfToken?.let { header("X-CSRF-Token", it) }
                setBody(
                    MultiPartFormDataContent(
                        formData {
                            extraFields.forEach { (key, value) ->
                                append(key, value)
                            }
                            append(
                                key = "file",
                                value = bytes,
                                headers = Headers.build {
                                    append(HttpHeaders.ContentType, mimeType)
                                    append(
                                        HttpHeaders.ContentDisposition,
                                        "filename=\"$fileName\"",
                                    )
                                },
                            )
                        },
                    ),
                )
            }
        } catch (e: Exception) {
            Log.e(TAG, "上传失败: ${e.message}", e)
            throw ApiException.NetworkError(e.message ?: "网络错误")
        }

        val text = response.bodyAsText()
        if (!response.status.isSuccess()) {
            Log.e(TAG, "上传 HTTP ${response.status.value}: $text")
            throw ApiException.HttpError(response.status.value, text)
        }
        return text
    }
}

/**
 * API 异常
 */
sealed class ApiException(message: String) : Exception(message) {
    /** 网络错误（连接失败、超时等） */
    class NetworkError(message: String) : ApiException(message)

    /** HTTP 错误（4xx/5xx） */
    class HttpError(val statusCode: Int, val responseText: String) :
        ApiException("HTTP $statusCode: $responseText")
}
