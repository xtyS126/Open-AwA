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
 * 1. 启动内嵌 Chaquopy Python 后端（FastAPI + uvicorn），委托给 [EmbeddedBackend]
 * 2. 管理后端端口（动态分配 8000-8100 范围，由 chaquopy_bootstrap 自动选择）
 * 3. 提供后端就绪状态（[isReady] StateFlow）
 * 4. 选择内嵌/远程后端（[resolveBaseUrl]）
 *
 * 后端启动流程：
 * Application.onCreate() → BackendManager.initialize() →
 *   EmbeddedBackend.start() → 子线程启动 Chaquopy → 端口写入 → 前端轮询 /api/system/ping
 *
 * 离线降级：
 * 内嵌后端启动失败时（[EmbeddedBackend.state] 变为 FAILED），自动降级到远程后端，
 * 由用户在设置页配置 BASE_URL。
 */
object BackendManager {
    private const val TAG = "BackendManager"
    private const val PREFS_NAME = "backend_prefs"
    private const val KEY_REMOTE_URL = "remote_url"
    private const val DEFAULT_REMOTE_URL = "http://192.168.1.100:8000"

    private lateinit var appContext: Context

    /** 后端就绪状态（仅内嵌后端就绪时为 true，远程后端不修改此状态） */
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
     *
     * 启动 [EmbeddedBackend]，订阅其状态变化自动同步 [isReady] / [error] / [useRemote]。
     *
     * @param context Application 上下文
     */
    fun initialize(context: Context) {
        appContext = context.applicationContext
        Log.i(TAG, "BackendManager 初始化")

        // 订阅 EmbeddedBackend 状态：失败时降级到远程后端，就绪时同步 isReady
        // 这里使用同步读取，避免引入额外的协程作用域；前端通过 isReady StateFlow 观察变化
        // EmbeddedBackend 在子线程中更新状态，调用方应在主线程读取后通过 StateFlow collect
        val started = EmbeddedBackend.start(appContext)
        if (!started) {
            // EmbeddedBackend 被禁用（构建期降级）或正在启动但未就绪，先标记为远程模式
            Log.w(TAG, "内嵌后端未启动，降级到远程后端模式")
            _useRemote.value = true
        }

        // 通过定时检查同步 EmbeddedBackend.state 到本地 StateFlow
        // 简化设计：在 resolveBaseUrl 时按需检查 EmbeddedBackend.state，
        // 同时提供 StateFlow 供前端轮询
        syncEmbeddedState()
    }

    /**
     * 同步 [EmbeddedBackend] 的状态到本地 StateFlow
     *
     * 应在每次需要查询后端状态前调用一次。
     */
    private fun syncEmbeddedState() {
        when (EmbeddedBackend.state.value) {
            EmbeddedBackend.State.READY -> {
                _isReady.value = true
                _error.value = null
                // 内嵌后端就绪，确保使用内嵌模式
                _useRemote.value = false
            }
            EmbeddedBackend.State.FAILED -> {
                _isReady.value = false
                _error.value = EmbeddedBackend.error.value
                // 启动失败，降级到远程
                _useRemote.value = true
                Log.w(TAG, "内嵌后端启动失败，降级到远程后端: ${_error.value}")
            }
            EmbeddedBackend.State.STARTING -> {
                // 启动中，保持当前状态
                Log.d(TAG, "内嵌后端启动中...")
            }
            EmbeddedBackend.State.IDLE -> {
                // 未启动，保持当前状态
            }
        }
    }

    /**
     * 刷新后端状态
     *
     * 前端轮询 /api/system/ping 失败时可调用此方法重新同步状态。
     */
    fun refreshState() {
        syncEmbeddedState()
    }

    /**
     * 获取后端 BaseUrl
     *
     * 内嵌后端返回 http://127.0.0.1:port，远程后端返回用户配置的 URL。
     * 内嵌模式启用时自动同步最新状态。
     *
     * @return 后端 BaseUrl，未就绪时返回空字符串
     */
    fun resolveBaseUrl(): String {
        // 同步 EmbeddedBackend 状态，确保使用最新值
        syncEmbeddedState()
        return if (_useRemote.value) {
            getRemoteUrl()
        } else {
            val port = getEmbeddedPort()
            if (port > 0) "http://127.0.0.1:$port" else ""
        }
    }

    /**
     * 获取内嵌后端端口
     *
     * 委托给 [EmbeddedBackend]，从 SharedPreferences 读取。
     * 若未分配则返回 0（前端会显示"后端未启动"）。
     */
    fun getEmbeddedPort(): Int {
        if (!::appContext.isInitialized) return 0
        return EmbeddedBackend.getPort(appContext)
    }

    /**
     * 获取内嵌后端的 API Key
     *
     * 前端通过此 key 跳过登录页自动认证（移动端单用户场景）。
     */
    fun getEmbeddedApiKey(): String {
        if (!::appContext.isInitialized) return ""
        return EmbeddedBackend.getApiKey(appContext)
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
        if (!useRemote) {
            // 切回内嵌时同步状态
            syncEmbeddedState()
        }
    }
}
