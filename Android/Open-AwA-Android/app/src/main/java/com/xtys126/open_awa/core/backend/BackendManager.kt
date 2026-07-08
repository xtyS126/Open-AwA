package com.xtys126.open_awa.core.backend

import android.content.Context
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 后端管理器
 *
 * 负责：
 * 1. 启动内嵌 Chaquopy Python 后端（FastAPI + uvicorn）
 * 2. 管理后端端口（动态分配 8000-8100 范围）
 * 3. 提供后端就绪状态（[isReady] StateFlow）
 * 4. 选择内嵌/远程后端（[resolveBaseUrl]）
 *
 * 后端启动流程：
 * Application.onCreate() → BackendManager.initialize() →
 *   启动 Chaquopy 子线程 → 端口写入 → 前端轮询 /api/system/ping
 *
 * 离线降级：
 * 内嵌后端启动失败时，自动降级到远程后端，由用户在设置页配置 BASE_URL
 */
object BackendManager {
    private const val TAG = "BackendManager"
    private const val PREFS_NAME = "backend_prefs"
    private const val KEY_PORT = "embedded_port"
    private const val KEY_REMOTE_URL = "remote_url"
    private const val DEFAULT_REMOTE_URL = "http://192.168.1.100:8000"
    private const val PORT_RANGE_START = 8000
    private const val PORT_RANGE_END = 8100

    private lateinit var appContext: Context

    /** 后端就绪状态 */
    private val _isReady = MutableStateFlow(false)
    val isReady: StateFlow<Boolean> = _isReady.asStateFlow()

    /** 后端启动错误信息 */
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    /** 是否使用远程后端（true=远程，false=内嵌） */
    private val _useRemote = MutableStateFlow(false)
    val useRemote: StateFlow<Boolean> = _useRemote.asStateFlow()

    /**
     * 初始化后端
     * @param context Application 上下文
     */
    fun initialize(context: Context) {
        appContext = context.applicationContext
        Log.i(TAG, "BackendManager 初始化")
        // TODO: 启动 Chaquopy 内嵌后端（第二阶段实现）
        // 当前阶段先标记为就绪，让前端能进入登录页
        _isReady.value = true
    }

    /**
     * 获取后端 BaseUrl
     * @return 内嵌后端返回 http://127.0.0.1:port，远程后端返回用户配置的 URL
     */
    fun resolveBaseUrl(): String {
        return if (_useRemote.value) {
            getRemoteUrl()
        } else {
            val port = getEmbeddedPort()
            "http://127.0.0.1:$port"
        }
    }

    /**
     * 获取内嵌后端端口
     * 若未分配则返回 0（前端会显示"后端未启动"）
     */
    fun getEmbeddedPort(): Int {
        val prefs = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getInt(KEY_PORT, 0)
    }

    /**
     * 设置内嵌后端端口
     */
    fun setEmbeddedPort(port: Int) {
        val prefs = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putInt(KEY_PORT, port).apply()
        Log.i(TAG, "内嵌后端端口: $port")
    }

    /**
     * 获取远程后端 URL
     */
    fun getRemoteUrl(): String {
        val prefs = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(KEY_REMOTE_URL, DEFAULT_REMOTE_URL) ?: DEFAULT_REMOTE_URL
    }

    /**
     * 设置远程后端 URL
     */
    fun setRemoteUrl(url: String) {
        val prefs = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit().putString(KEY_REMOTE_URL, url).apply()
        Log.i(TAG, "远程后端 URL: $url")
    }

    /**
     * 切换内嵌/远程后端
     */
    fun setUseRemote(useRemote: Boolean) {
        _useRemote.value = useRemote
        Log.i(TAG, "切换后端模式: ${if (useRemote) "远程" else "内嵌"}")
    }
}
