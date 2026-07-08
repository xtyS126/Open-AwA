package com.xtys126.open_awa.core.theme

import androidx.compose.ui.graphics.Color

/**
 * 设计令牌 - 颜色体系
 *
 * 对应 frontend/src/styles/tokens.css 中的 --color-* 变量
 * 所有颜色集中定义，组件通过 [OpenAwAColors] 访问
 */

// 亮色主题颜色
val ColorPrimary = Color(0xFF3B82F6)
val ColorPrimaryHover = Color(0xFF2563EB)
val ColorPrimaryDark = Color(0xFF1D4ED8)
val ColorPrimaryRing = Color(0x333B82F6) // 20% 透明度

val ColorBg = Color(0xFFFFFFFF)
val ColorBgSecondary = Color(0xFFF8FAFC)
val ColorBgTertiary = Color(0xFFF1F5F9)

val ColorText = Color(0xFF0F172A)
val ColorTextSecondary = Color(0xFF475569)
val ColorTextTertiary = Color(0xFF94A3B8)

val ColorBorder = Color(0xFFE2E8F0)
val ColorBorderSubtle = Color(0xFFF1F5F9)

// 语义色 - 成功
val ColorSuccess = Color(0xFF10B981)
val ColorSuccessBg = Color(0x1F10B981) // 12% 透明度

// 语义色 - 错误
val ColorError = Color(0xFFEF4444)
val ColorErrorBg = Color(0x1FEF4444)
val ColorErrorStrong = Color(0xFFB91C1C)

// 语义色 - 警告
val ColorWarning = Color(0xFFF59E0B)
val ColorWarningBg = Color(0x29F59E0B) // 16% 透明度

// 语义色 - 信息
val ColorInfo = Color(0xFF3B82F6)
val ColorInfoBg = Color(0xFFDBEAFE)

// 遮罩
val ColorOverlay = Color(0x802E3A52) // 50% 透明度

// 暗色主题颜色覆写
val ColorPrimaryDark_ = Color(0xFF3B82F6)
val ColorPrimaryHoverDark = Color(0xFF60A5FA)
val ColorPrimaryRingDark = Color(0x4D3B82F6) // 30% 透明度

val ColorBgDark = Color(0xFF0F172A)
val ColorBgSecondaryDark = Color(0xFF1E293B)
val ColorBgTertiaryDark = Color(0xFF334155)

val ColorTextDark = Color(0xFFF8FAFC)
val ColorTextSecondaryDark = Color(0xFFCBD5E1)
val ColorTextTertiaryDark = Color(0xFF94A3B8)

val ColorBorderDark = Color(0xFF334155)
val ColorBorderSubtleDark = Color(0xFF1E293B)

val ColorSuccessDark = Color(0xFF34D399)
val ColorSuccessBgDark = Color(0x3334D399)

val ColorErrorDark = Color(0xFFF87171)
val ColorErrorBgDark = Color(0x33F87171)
val ColorErrorStrongDark = Color(0xFFEF4444)

val ColorWarningDark = Color(0xFFFBBF24)
val ColorWarningBgDark = Color(0x33FBBF24)

val ColorInfoDark = Color(0xFF60A5FA)
val ColorInfoBgDark = Color(0x3360A5FA)

val ColorOverlayDark = Color(0xB3000000) // 70% 透明度
