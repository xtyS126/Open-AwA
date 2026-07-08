package com.xtys126.open_awa

import android.app.Application
import android.util.Log
import com.xtys126.open_awa.core.backend.BackendManager

/**
 * 应用入口
 *
 * 服务器中心多端一体架构：本应用为瘦客户端，所有业务逻辑由服务器后端提供。
 * [BackendManager.initialize] 加载用户配置的服务器后端 URL。
 */
class OpenAwAApplication : Application() {
    companion object {
        private const val TAG = "OpenAwAApp"
    }

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "Application onCreate: 初始化后端管理器（服务器中心模式）")
        BackendManager.initialize(this)
    }
}
