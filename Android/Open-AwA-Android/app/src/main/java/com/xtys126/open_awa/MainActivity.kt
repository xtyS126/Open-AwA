package com.xtys126.open_awa

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.core.view.WindowCompat
import com.xtys126.open_awa.core.nav.AppShell
import com.xtys126.open_awa.core.theme.OpenAwATheme

/**
 * 主 Activity - 单 Activity 架构
 *
 * 所有页面通过 Jetpack Compose + Navigation 在此 Activity 内渲染
 * 主题由 [OpenAwATheme] 提供，导航外壳由 [AppShell] 提供
 */
class MainActivity : ComponentActivity() {
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
        setContent {
            OpenAwATheme {
                AppShell()
            }
        }
    }
}
