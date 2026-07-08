package com.xtys126.open_awa.core.backend

import android.util.Log
import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.engine.cio.CIO
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.plugins.logging.LogLevel
import io.ktor.client.plugins.logging.Logging
import io.ktor.client.request.HttpRequestBuilder
import io.ktor.client.request.header
import io.ktor.client.request.request
import io.ktor.client.request.setBody
import io.ktor.client.statement.HttpResponse
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpMethod
import io.ktor.http.isSuccess
import io.ktor.serialization.kotlinx.json.json
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

/**
 * API 客户端
 *
 * 封装 Ktor HTTP 客户端，统一处理：
 * 1. BaseUrl 解析（[BackendManager.resolveBaseUrl]）
 * 2. JSON 序列化/反序列化
 * 3. CSRF 令牌/Authorization 令牌注入
 * 4. 错误处理
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

    /** Ktor HTTP 客户端（懒加载） */
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
     * 设置 CSRF 令牌
     */
    fun setCsrfToken(token: String?) {
        csrfToken = token
    }

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
     * PUT 请求
     */
    suspend fun put(path: String, body: Any? = null): String =
        request(path, HttpMethod.Put, body)

    /**
     * DELETE 请求
     */
    suspend fun delete(path: String): String = request(path, HttpMethod.Delete)
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
