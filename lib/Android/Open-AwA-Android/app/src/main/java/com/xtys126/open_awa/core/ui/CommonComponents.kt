package com.xtys126.open_awa.core.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.core.theme.LocalBrandGradient

/**
 * 通用 UI 组件
 *
 * 提供四个跨页面复用的组件，统一加载/错误/空状态/分组卡片的视觉风格：
 * - [LoadingBox] 加载中占位
 * - [ErrorBox] 错误提示 + 重试
 * - [EmptyBox] 空状态占位
 * - [SectionCard] 分组卡片
 *
 * 2026-07-09 UI 优化：
 * - [LoadingBox] 使用品牌色 [MaterialTheme.colorScheme.primary]
 * - [ErrorBox] 圆形图标背景 + 错误色按钮
 * - [EmptyBox] 渐变背景圆形图标
 * - [SectionCard] 圆角 16dp + 阴影 1dp + 标题大写
 */

/**
 * 加载中占位
 *
 * 居中显示 [CircularProgressIndicator]，铺满父布局
 *
 * 2026-07-09 UI 优化：使用品牌色，提升识别度
 */
@Composable
fun LoadingBox(
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        CircularProgressIndicator(
            color = MaterialTheme.colorScheme.primary,
            strokeWidth = 3.dp,
        )
    }
}

/**
 * 错误提示 + 重试
 *
 * 居中显示错误图标 + 错误消息 + 重试按钮
 *
 * 2026-07-09 UI 优化：错误图标用 errorContainer 圆形背景包裹，更醒目
 *
 * @param message 错误消息
 * @param onRetry 重试回调
 */
@Composable
fun ErrorBox(
    message: String,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            // 错误图标用 errorContainer 圆形背景包裹
            Box(
                modifier = Modifier
                    .size(72.dp)
                    .clip(RoundedCornerShape(36.dp))
                    .background(MaterialTheme.colorScheme.errorContainer),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.Outlined.ErrorOutline,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.error,
                    modifier = Modifier.size(36.dp),
                )
            }
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.height(20.dp))
            Button(
                onClick = onRetry,
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.error,
                ),
            ) {
                Text(text = "重试")
            }
        }
    }
}

/**
 * 空状态占位
 *
 * 居中显示图标 + 标题 + 可选操作按钮
 *
 * 2026-07-09 UI 优化：图标用品牌渐变圆形背景包裹，提供品牌感
 *
 * @param icon 图标
 * @param title 标题
 * @param actionText 操作按钮文字（可空，与 [onAction] 同时提供时才显示按钮）
 * @param onAction 操作回调（可空）
 */
@Composable
fun EmptyBox(
    icon: ImageVector,
    title: String,
    modifier: Modifier = Modifier,
    actionText: String? = null,
    onAction: (() -> Unit)? = null,
) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .padding(24.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
        ) {
            // 图标用品牌渐变圆形背景包裹
            Box(
                modifier = Modifier
                    .size(88.dp)
                    .clip(RoundedCornerShape(44.dp))
                    .background(LocalBrandGradient.current),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimary,
                    modifier = Modifier.size(44.dp),
                )
            }
            Spacer(modifier = Modifier.height(20.dp))
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Medium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            if (actionText != null && onAction != null) {
                Spacer(modifier = Modifier.height(20.dp))
                Button(onClick = onAction) {
                    Text(text = actionText)
                }
            }
        }
    }
}

/**
 * 分组卡片
 *
 * 用于 SettingsScreen 的分组展示，包含标题 + 内容槽
 *
 * 2026-07-09 UI 优化：
 * - 圆角升级为 16dp（更现代）
 * - 阴影 1dp（轻微浮起）
 * - 标题大写 + SemiBold + tertiary 色
 * - 标题下方增加 8dp 间隔
 *
 * @param title 分组标题
 * @param modifier 修饰符
 * @param content 内容槽（放最后以支持 trailing lambda 调用）
 */
@Composable
fun SectionCard(
    title: String,
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit,
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
        elevation = CardDefaults.cardElevation(
            defaultElevation = 1.dp,
        ),
        shape = RoundedCornerShape(16.dp),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
        ) {
            Text(
                text = title.uppercase(),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(modifier = Modifier.height(12.dp))
            content()
        }
    }
}
