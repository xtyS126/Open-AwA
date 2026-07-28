package com.xtys126.open_awa.core.backend

import android.content.Context
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 后端管理器（服务器中心多端一体架构）
 *
 * 职责：
 * 1. 管理服务器后端 BaseUrl（用户在设置页配置，默认 http://192.168.1.100:8000）
 * 2. 提供就绪状态（[isReady] 在 [initialize] 后始终为 true，表示配置已加载）
 * 3. 持久化 BaseUrl 到 SharedPreferences
 *
 * 架构说明：
 * 本应用为瘦客户端，所有业务逻辑（auth/chat/billing/skills/plugins/memory/acp）
 * 均在服务器后端运行。Android 端通过统一 REST API + SSE/WebSocket 接入，
 * 与 Web/桌面端对等，共享同一份用户数据与会话状态。
 */
object BackendManager {
    private const val TAG = "BackendManager"
    private const val PREFS_NAME = "backend_prefs"
    private const val KEY_REMOTE_URL = "remote_url"
    private const val DEFAULT_REMOTE_URL = "http://192.168.1.100:8000"

    private lateinit var appContext: Context

    /** 后端配置就绪状态（[initialize] 调用后为 true） */
    private val _isReady = MutableStateFlow(false)
    val isReady: StateFlow<Boolean> = _isReady.asStateFlow()

    /** 后端错误信息（目前仅占位，后续可扩展为连通性检测） */
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    /**
     * 初始化后端管理器
     *
     * 加载持久化的 BaseUrl，标记就绪。前端通过 [isReady] 观察初始化完成。
     *
     * @param context Application 上下文
     */
    fun initialize(context: Context) {
        appContext = context.applicationContext
        Log.i(TAG, "BackendManager 初始化：服务器中心模式，BaseUrl=${getRemoteUrl()}")
        _isReady.value = true
    }

    /**
     * 获取后端 BaseUrl
     *
     * 始终返回用户配置的服务器后端 URL。
     *
     * @return 后端 BaseUrl
     */
    fun resolveBaseUrl(): String = getRemoteUrl()

    /**
     * 获取服务器后端 URL
     */
    fun getRemoteUrl(): String {
        if (!::appContext.isInitialized) return DEFAULT_REMOTE_URL
        val prefs = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_REMOTE_URL, DEFAULT_REMOTE_URL) ?: DEFAULT_REMOTE_URL
    }

    /**
     * 设置服务器后端 URL
     */
    fun setRemoteUrl(url: String) {
        val prefs = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(KEY_REMOTE_URL, url).apply()
        Log.i(TAG, "服务器后端 URL: $url")
    }
}
