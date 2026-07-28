package com.xtys126.open_awa

import android.app.Application
import android.util.Log
import com.xtys126.open_awa.core.backend.BackendManager
import com.xtys126.open_awa.core.notification.SystemNotifier

/**
 * 应用入口
 *
 * 服务器中心多端一体架构：本应用为瘦客户端，所有业务逻辑由服务器后端提供。
 * [BackendManager.initialize] 加载用户配置的服务器后端 URL。
 * [SystemNotifier.ensureChannel] 预创建 inbox 通知渠道，确保首条推送能正常显示。
 */
class OpenAwAApplication : Application() {
    companion object {
        private const val TAG = "OpenAwAApp"
    }

    override fun onCreate() {
        super.onCreate()
        Log.i(TAG, "Application onCreate: 初始化后端管理器（服务器中心模式）")
        BackendManager.initialize(this)
        // 预创建 inbox 通知渠道，避免首条 task_result 推送因渠道未创建而丢失
        SystemNotifier.ensureChannel(this)
    }
}
