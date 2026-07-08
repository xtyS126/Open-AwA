package com.xtys126.open_awa.core.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * 亮色主题配色方案
 * 对应 tokens.css :root 选择器下的 --color-* 变量
 */
private val LightColorScheme = lightColorScheme(
    primary = ColorPrimary,
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFDBEAFE),
    onPrimaryContainer = Color(0xFF1D4ED8),
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
    surface = ColorBg,
    onSurface = ColorText,
    surfaceVariant = ColorBgSecondary,
    onSurfaceVariant = ColorTextSecondary,
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
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFF1E3A8A),
    onPrimaryContainer = Color(0xFFDBEAFE),
    secondary = ColorSuccessDark,
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = ColorSuccessBgDark,
    onSecondaryContainer = Color(0xFF34D399),
    tertiary = Color(0xFFA78BFA),
    onTertiary = Color(0xFFFFFFFF),
    error = ColorErrorDark,
    onError = Color(0xFFFFFFFF),
    errorContainer = ColorErrorBgDark,
    onErrorContainer = ColorErrorStrongDark,
    background = ColorBgDark,
    onBackground = ColorTextDark,
    surface = ColorBgDark,
    onSurface = ColorTextDark,
    surfaceVariant = ColorBgSecondaryDark,
    onSurfaceVariant = ColorTextSecondaryDark,
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
    MaterialTheme(
        colorScheme = colorScheme,
        typography = AppTypography,
        content = content,
    )
}
