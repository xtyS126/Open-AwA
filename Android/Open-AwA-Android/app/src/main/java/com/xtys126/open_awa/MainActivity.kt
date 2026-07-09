package com.xtys126.open_awa

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import com.xtys126.open_awa.core.nav.AppShell
import com.xtys126.open_awa.core.theme.OpenAwATheme

/**
 * 主 Activity - 单 Activity 架构
 *
 * 所有页面通过 Jetpack Compose + Navigation 在此 Activity 内渲染
 * 主题由 [OpenAwATheme] 提供，导航外壳由 [AppShell] 提供
 *
 * 启动时申请运行时权限：
 * - Android 13+（API 33+）：[Manifest.permission.POST_NOTIFICATIONS]，
 *   用于定时任务完成提醒、收件箱实时推送的系统通知栏通知
 *   （Android 12 及以下版本在 manifest 声明即可，无需运行时申请）
 */
class MainActivity : ComponentActivity() {

    /**
     * 系统通知权限申请结果 Launcher
     *
     * 通过 ActivityResultContracts.RequestPermission 在 setContent 之前注册，
     * 避免在 Composable 内注册导致的 lifecycle 冲突。
     * 申请结果仅记录日志，不阻塞主流程（用户拒绝时通知不显示，应用其他功能不受影响）。
     */
    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                android.util.Log.i("MainActivity", "POST_NOTIFICATIONS 权限已授予")
            } else {
                android.util.Log.w("MainActivity", "POST_NOTIFICATIONS 权限被拒绝，系统通知将不显示")
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // 边到边布局，让 Compose 接管状态栏/导航栏 insets
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.auto(
                android.graphics.Color.TRANSPARENT,
                android.graphics.Color.TRANSPARENT,
            ),
            navigationBarStyle = SystemBarStyle.auto(
                android.graphics.Color.TRANSPARENT,
                android.graphics.Color.TRANSPARENT,
            ),
        )
        WindowCompat.setDecorFitsSystemWindows(window, false)
        // 申请系统通知权限（Android 13+）
        requestNotificationPermissionIfNeeded()
        setContent {
            OpenAwATheme {
                AppShell()
            }
        }
    }

    /**
     * 申请 POST_NOTIFICATIONS 权限（Android 13+ 必需）
     *
     * 仅在以下条件全部满足时弹出权限对话框：
     * 1. 当前系统版本 >= Android 13（API 33）
     * 2. 当前未授予 POST_NOTIFICATIONS 权限
     *
     * 已授予时不重复申请，避免打扰用户。
     */
    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return
        val granted = ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }
}
