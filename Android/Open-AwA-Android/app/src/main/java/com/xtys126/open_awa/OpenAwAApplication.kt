package com.xtys126.open_awa

import android.app.Application
import android.util.Log
import com.xtys126.open_awa.core.backend.BackendManager

/**
 * 应用入口
 *
 * 负责初始化全局状态，启动内嵌后端（Chaquopy Python）
 * 后端启动异步进行，前端通过 [BackendManager.isReady] 观察就绪状态
 */
class OpenAwAApplication : Application() {
    companion object {
        private const val TAG = "OpenAwAApp"
    }

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "Application onCreate: 初始化后端管理器")
        // 初始化后端管理器，启动内嵌 Python 后端
        BackendManager.initialize(this)
    }
}
