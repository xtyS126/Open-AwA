package com.xtys126.open_awa.core.theme

import androidx.compose.ui.graphics.Color

/**
 * 设计令牌 - 颜色体系
 *
 * 对应 frontend/src/styles/tokens.css 中的 --color-* 变量
 * 所有颜色集中定义，组件通过 [OpenAwAColors] 访问
 *
 * 2026-07-09 UI 优化：
 * - 主品牌色升级为更深的靛蓝（Indigo 600 #4F46E5），提升识别度与品牌感
 * - 补充渐变色 [BrandGradientStart]/[BrandGradientEnd]，用于 Logo/按钮渐变
 * - 表面层次更清晰：surface / surfaceVariant / surfaceContainer 区分
 */

// ==================== 亮色主题 ====================

// 主品牌色（Indigo 600 系）
val ColorPrimary = Color(0xFF4F46E5)
val ColorPrimaryHover = Color(0xFF4338CA)
val ColorPrimaryDark = Color(0xFF3730A3)
val ColorPrimaryRing = Color(0x334F46E5) // 20% 透明度

// 品牌渐变（Logo / 主按钮强调色）
val BrandGradientStart = Color(0xFF6366F1) // Indigo 500
val BrandGradientEnd = Color(0xFF8B5CF6) // Violet 500

// 表面与背景
val ColorBg = Color(0xFFFAFAFA)
val ColorBgSecondary = Color(0xFFF4F4F5)
val ColorBgTertiary = Color(0xFFE4E4E7)

// 文本
val ColorText = Color(0xFF18181B)
val ColorTextSecondary = Color(0xFF52525B)
val ColorTextTertiary = Color(0xFFA1A1AA)

// 边框
val ColorBorder = Color(0xFFE4E4E7)
val ColorBorderSubtle = Color(0xFFF4F4F5)

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

// ==================== 暗色主题 ====================

val ColorPrimaryDark_ = Color(0xFF818CF8) // Indigo 400（暗色背景上更亮）
val ColorPrimaryHoverDark = Color(0xFFA5B4FC)
val ColorPrimaryRingDark = Color(0x4D818CF8) // 30% 透明度

// 暗色品牌渐变
val BrandGradientStartDark = Color(0xFF818CF8)
val BrandGradientEndDark = Color(0xFFA78BFA)

val ColorBgDark = Color(0xFF09090B)
val ColorBgSecondaryDark = Color(0xFF18181B)
val ColorBgTertiaryDark = Color(0xFF27272A)

val ColorTextDark = Color(0xFFFAFAFA)
val ColorTextSecondaryDark = Color(0xFFD4D4D8)
val ColorTextTertiaryDark = Color(0xFFA1A1AA)

val ColorBorderDark = Color(0xFF27272A)
val ColorBorderSubtleDark = Color(0xFF18181B)

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
