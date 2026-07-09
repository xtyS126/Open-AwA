package com.xtys126.open_awa.core.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Brush

/**
 * 品牌渐变画刷（亮色主题）
 *
 * 用于 Logo / 主按钮 / 顶栏强调装饰，提供品牌识别度。
 * 通过 [LocalBrandGradient] 在 Compose 树中传递，避免每个组件重复构造。
 */
val LocalBrandGradient = staticCompositionLocalOf<Brush> {
    Brush.linearGradient(listOf(BrandGradientStart, BrandGradientEnd))
}

/**
 * 品牌渐变画刷（暗色主题）
 */
val LocalBrandGradientDark = staticCompositionLocalOf<Brush> {
    Brush.linearGradient(listOf(BrandGradientStartDark, BrandGradientEndDark))
}

/**
 * 亮色主题配色方案
 * 对应 tokens.css :root 选择器下的 --color-* 变量
 *
 * 2026-07-09 UI 优化：
 * - primaryContainer 改为更浅的 Indigo 100，提升与 primary 的对比层次
 * - surfaceVariant 改为 Zinc 100，作为次级背景
 * - 新增 surfaceContainer（Zinc 200），用于卡片悬浮态
 */
private val LightColorScheme = lightColorScheme(
    primary = ColorPrimary,
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFE0E7FF),
    onPrimaryContainer = Color(0xFF3730A3),
    secondary = Color(0xFF10B981),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = ColorSuccessBg,
    onSecondaryContainer = Color(0xFF047857),
    tertiary = Color(0xFF8B5CF6),
    onTertiary = Color(0xFFFFFFFF),
    error = ColorError,
    onError = Color(0xFFFFFFFF),
    errorContainer = ColorErrorBg,
    onErrorContainer = ColorErrorStrong,
    background = ColorBg,
    onBackground = ColorText,
    surface = Color(0xFFFFFFFF),
    onSurface = ColorText,
    surfaceVariant = ColorBgSecondary,
    onSurfaceVariant = ColorTextSecondary,
    surfaceContainer = ColorBgTertiary,
    outline = ColorBorder,
    outlineVariant = ColorBorderSubtle,
    scrim = ColorOverlay,
)

/**
 * 暗色主题配色方案
 * 对应 tokens.css .dark 选择器下的 --color-* 变量
 */
private val DarkColorScheme = darkColorScheme(
    primary = ColorPrimaryDark_,
    onPrimary = Color(0xFF1E1B4B),
    primaryContainer = Color(0xFF3730A3),
    onPrimaryContainer = Color(0xFFE0E7FF),
    secondary = ColorSuccessDark,
    onSecondary = Color(0xFF052E1F),
    secondaryContainer = ColorSuccessBgDark,
    onSecondaryContainer = Color(0xFF34D399),
    tertiary = Color(0xFFA78BFA),
    onTertiary = Color(0xFF2E1065),
    error = ColorErrorDark,
    onError = Color(0xFFFFFFFF),
    errorContainer = ColorErrorBgDark,
    onErrorContainer = ColorErrorStrongDark,
    background = ColorBgDark,
    onBackground = ColorTextDark,
    surface = ColorBgSecondaryDark,
    onSurface = ColorTextDark,
    surfaceVariant = ColorBgTertiaryDark,
    onSurfaceVariant = ColorTextSecondaryDark,
    surfaceContainer = Color(0xFF3F3F46),
    outline = ColorBorderDark,
    outlineVariant = ColorBorderSubtleDark,
    scrim = ColorOverlayDark,
)

/**
 * 应用主题入口
 *
 * @param darkTheme 是否使用暗色主题，默认跟随系统
 * @param content Compose 内容
 */
@Composable
fun OpenAwATheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme
    val brandGradient = if (darkTheme) {
        Brush.linearGradient(listOf(BrandGradientStartDark, BrandGradientEndDark))
    } else {
        Brush.linearGradient(listOf(BrandGradientStart, BrandGradientEnd))
    }
    CompositionLocalProvider(LocalBrandGradient provides brandGradient) {
        MaterialTheme(
            colorScheme = colorScheme,
            typography = AppTypography,
            content = content,
        )
    }
}
