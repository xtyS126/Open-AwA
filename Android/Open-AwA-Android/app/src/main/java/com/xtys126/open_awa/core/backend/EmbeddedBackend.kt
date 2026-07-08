package com.xtys126.open_awa.core.backend

import android.content.Context
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 内嵌后端启动器
 *
 * 通过 Chaquopy 调用 chaquopy_bootstrap.py 的 start_backend() 函数，
 * 在子线程中运行 FastAPI + uvicorn，监听 127.0.0.1:port。
 *
 * 启动流程：
 * 1. 初始化 Chaquopy Python 运行时（首次）
 * 2. 设置数据目录（应用私有目录）
 * 3. 调用 start_backend() 在子线程启动 uvicorn
 * 4. 读取 API Key 持久化到 SharedPreferences
 * 5. 端口持久化到 SharedPreferences
 *
 * 失败时设置 [error] StateFlow，由 [BackendManager] 决定是否降级到远程后端。
 *
 * 兼容性说明：
 * 当 Chaquopy 与 Gradle 9 不兼容时，构建期会降级为 ENABLED=false 的 stub，
 * 此对象仍可被调用，但 [start] 始终返回 false，由 [BackendManager] 自动降级到远程后端。
 *
 * TODO: Chaquopy 17.0.0 + Gradle 9 + AGP 9 兼容性待验证
 * 集成时恢复 ENABLED=true 并取消下方 Chaquopy 调用的注释
 */
object EmbeddedBackend {
    private const val TAG = "EmbeddedBackend"
    private const val PREFS_NAME = "openawa_backend"
    private const val PREF_PORT = "backend_port"
    private const val PREF_STARTED = "backend_started"
    private const val PREF_API_KEY = "backend_api_key"

    /**
     * 启动状态
     */
    enum class State {
        /** 未启动 */
        IDLE,
        /** 启动中 */
        STARTING,
        /** 已就绪 */
        READY,
        /** 启动失败或被禁用 */
        FAILED
    }

    /**
     * 是否启用 Chaquopy 内嵌后端（构建期决定，降级时改为 false）
     *
     * TODO: Chaquopy 17.0.0 与 Gradle 9 + AGP 9 兼容性待验证
     * 集成时改回 true 并恢复下方 Chaquopy 调用代码
     */
    private const val ENABLED = false

    private val _state = MutableStateFlow(State.IDLE)
    val state: StateFlow<State> = _state.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    /**
     * 启动内嵌后端
     *
     * 在子线程中执行，调用后立即返回。调用者可通过 [state] 观察启动进度。
     *
     * @param context Application 上下文
     * @return true 表示已成功触发启动（不一定就绪），false 表示被禁用或参数错误
     */
    fun start(context: Context): Boolean {
        if (!ENABLED) {
            Log.w(TAG, "Chaquopy 内嵌后端已禁用，降级到远程后端")
            _state.value = State.FAILED
            _error.value = "Chaquopy 已禁用（构建期降级）"
            return false
        }

        // 已就绪或正在启动，避免重复启动
        when (_state.value) {
            State.READY -> {
                Log.i(TAG, "内嵌后端已就绪，跳过启动")
                return true
            }
            State.STARTING -> {
                Log.i(TAG, "内嵌后端正在启动，跳过重复调用")
                return false
            }
            else -> {
                // IDLE / FAILED 允许重新启动
            }
        }

        _state.value = State.STARTING
        _error.value = null

        // 重置上次启动遗留的状态：上次启动遗留的 backend_started=true 会让前端误以为后端已就绪，
        // 跳过 waitForEmbeddedBackend 轮询，导致首次 API 请求失败。
        // 等本次 start_backend 返回后，再设为 true。
        val appContext = context.applicationContext
        val prefs = appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        prefs.edit()
            .putBoolean(PREF_STARTED, false)
            .putInt(PREF_PORT, 0)
            .putString(PREF_API_KEY, "")
            .apply()

        val dataDir = appContext.filesDir.absolutePath
        Log.i(TAG, "数据目录: $dataDir")

        // 在子线程中启动后端，避免阻塞 UI
        // TODO: Chaquopy 集成后取消下方注释恢复 Python 调用
        /*
        Thread({
            try {
                // 1. 初始化 Chaquopy Python 运行时（仅首次需要）
                if (!Python.isStarted()) {
                    Python.start(AndroidPlatform(appContext))
                }

                val py = Python.getInstance()

                // 2. 设置数据目录（必须在 start_backend 之前）
                py.getModule("chaquopy_bootstrap").callAttr("set_data_dir", dataDir)

                // 3. 启动后端（callAttr 会阻塞至 _backend_started 或 _backend_error）
                val portObj = py.getModule("chaquopy_bootstrap").callAttr("start_backend")
                val port = portObj.toInt()
                Log.i(TAG, "内嵌后端已启动，端口: $port")

                // 4. 读取 API Key（首次启动时由 Python 侧生成并持久化）
                val apiKeyObj = py.getModule("chaquopy_bootstrap").callAttr("get_api_key")
                val apiKey = apiKeyObj.toString()

                // 5. 持久化端口与 API Key 到 SharedPreferences
                appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
                    .putInt(PREF_PORT, port)
                    .putBoolean(PREF_STARTED, true)
                    .putString(PREF_API_KEY, apiKey)
                    .apply()

                _state.value = State.READY
            } catch (e: Exception) {
                // 关键路径异常必须记录，不允许静默吞异常
                Log.e(TAG, "内嵌后端启动失败", e)
                _error.value = e.message ?: "未知错误"
                _state.value = State.FAILED
                // 标记启动失败
                appContext.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE).edit()
                    .putBoolean(PREF_STARTED, false)
                    .apply()
            }
        }, "OpenAwA-Backend-Boot").start()
        */

        // stub 模式：直接标记为失败，由 BackendManager 降级到远程后端
        _state.value = State.FAILED
        _error.value = "Chaquopy 已禁用（构建期降级）"

        return false
    }

    /**
     * 获取后端监听端口
     * @return 端口号，未启动时返回 0
     */
    fun getPort(context: Context): Int {
        val prefs = context.applicationContext
            .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getInt(PREF_PORT, 0)
    }

    /**
     * 后端是否已启动
     */
    fun isStarted(context: Context): Boolean {
        val prefs = context.applicationContext
            .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getBoolean(PREF_STARTED, false)
    }

    /**
     * 获取内嵌后端的 API Key
     *
     * 前端通过此 key 跳过登录页自动认证（移动端单用户场景）。
     * @return API Key 字符串，未启动时返回空字符串
     */
    fun getApiKey(context: Context): String {
        val prefs = context.applicationContext
            .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
        return prefs.getString(PREF_API_KEY, "") ?: ""
    }

    /**
     * 获取完整后端 URL
     * @return http://127.0.0.1:{port}，未启动时返回空字符串
     */
    fun getBaseUrl(context: Context): String {
        val port = getPort(context)
        return if (port > 0) "http://127.0.0.1:$port" else ""
    }
}
