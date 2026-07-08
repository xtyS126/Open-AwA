package com.xtys126.open_awa.features.inbox

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.DoneAll
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.TaskAlt
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.core.backend.WebSocketConnectionState
import com.xtys126.open_awa.data.AuthRepository
import com.xtys126.open_awa.data.Notification
import com.xtys126.open_awa.data.NotificationRepository
import com.xtys126.open_awa.data.NotificationType
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * 收件箱页
 *
 * 接入实时通知：
 * 1. 启动时通过 REST 拉取历史 inbox 消息（[NotificationRepository.listMessages]）
 * 2. 同时建立 WebSocket 连接，实时接收推送（[NotificationRepository.start]）
 * 3. WebSocket 推送的新通知插入列表顶部，带未读标记
 * 4. 点击通知调用 [NotificationRepository.markAsRead] 更新已读状态
 * 5. 顶部全部已读按钮调用 [NotificationRepository.markAllRead]
 *
 * 鉴权约束：WebSocket token 通过 Sec-WebSocket-Protocol 子协议传递，
 * 由 [NotificationRepository.start] 内部封装，UI 不感知。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun InboxScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    // Repository 实例（remember 保证跨 recompose 复用，避免重复创建）
    val notificationRepo = remember { NotificationRepository() }
    val authRepo = remember { AuthRepository(context.applicationContext) }

    // 消息列表（合并历史 + 实时推送），新增通知插入到顶部
    val messages = remember { mutableStateListOf<Notification>() }

    // 加载与错误状态
    var isLoading by remember { mutableStateOf(true) }
    var errorMessage by remember { mutableStateOf<String?>(null) }

    // WebSocket 连接状态（用于显示在线指示器）
    val connectionState by notificationRepo.connectionState.collectAsState()

    // 启动时拉取历史消息 + 启动 WebSocket 监听
    LaunchedEffect(Unit) {
        // 拉取历史 inbox 消息
        runCatching {
            notificationRepo.listMessages()
        }.onSuccess { response ->
            messages.clear()
            messages.addAll(response.messages)
            isLoading = false
        }.onFailure { e ->
            errorMessage = e.message ?: "拉取通知失败"
            isLoading = false
        }

        // 启动 WebSocket 实时监听（需要 access_token）
        runCatching {
            val token = authRepo.accessTokenFlow.first()
            if (token != null) {
                // 使用 "inbox" 作为虚拟 session_id 建立实时通道
                // 后端 chat ws 在 session_id 不存在时不会拒绝连接，
                // 此连接仅用于接收服务端广播的实时事件（如审批、任务结果）
                notificationRepo.start(token, sessionId = "inbox")

                // collect WebSocket 事件流，新通知实时插入列表顶部
                notificationRepo.collectEvents { notification ->
                    // 去重后插入顶部（同 id 通知可能是更新推送，覆盖旧条目）
                    messages.removeAll { it.id == notification.id }
                    messages.add(0, notification)
                }
            }
        }.onFailure { e ->
            // WebSocket 启动失败不阻塞 UI，仅记录错误
            errorMessage = "实时通道启动失败: ${e.message}"
        }
    }

    // 页面销毁时停止 WebSocket 监听，避免资源泄露
    DisposableEffect(Unit) {
        onDispose {
            notificationRepo.stop()
        }
    }

    // 未读消息数
    val unreadCount = messages.count { !it.read }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        BadgedBox(badge = {
                            if (unreadCount > 0) {
                                Badge { Text(text = "$unreadCount") }
                            }
                        }) {
                            Text(text = "收件箱", style = MaterialTheme.typography.titleMedium)
                        }
                        // 连接状态指示器
                        Spacer(modifier = Modifier.padding(start = 12.dp))
                        ConnectionStateIndicator(connectionState)
                    }
                },
                actions = {
                    IconButton(onClick = {
                        // 调用 REST 标记全部已读
                        scope.launch {
                            runCatching {
                                notificationRepo.markAllRead()
                            }.onSuccess {
                                // 本地同步更新已读状态
                                messages.indices.forEach { i ->
                                    messages[i] = messages[i].copy(read = true)
                                }
                                Toast.makeText(context, "已标记全部已读", Toast.LENGTH_SHORT).show()
                            }.onFailure { e ->
                                Toast.makeText(
                                    context,
                                    "标记失败: ${e.message}",
                                    Toast.LENGTH_SHORT,
                                ).show()
                            }
                        }
                    }) {
                        Icon(
                            imageVector = Icons.Outlined.DoneAll,
                            contentDescription = "全部已读",
                        )
                    }
                },
            )
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            when {
                isLoading -> {
                    // 加载中
                    CircularProgressIndicator(
                        modifier = Modifier.align(Alignment.Center),
                    )
                }

                messages.isEmpty() -> {
                    // 空列表
                    Text(
                        text = errorMessage ?: "暂无通知",
                        modifier = Modifier.align(Alignment.Center),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }

                else -> {
                    LazyColumn(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(horizontal = 16.dp, vertical = 8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        items(messages, key = { it.id }) { notification ->
                            NotificationCard(
                                notification = notification,
                                onClick = {
                                    // 已读则不重复调用
                                    if (notification.read) return@NotificationCard
                                    scope.launch {
                                        runCatching {
                                            notificationRepo.markAsRead(notification.id)
                                        }.onSuccess {
                                            // 本地同步更新已读状态
                                            val idx = messages.indexOfFirst { it.id == notification.id }
                                            if (idx >= 0) {
                                                messages[idx] = messages[idx].copy(read = true)
                                            }
                                        }.onFailure { e ->
                                            Toast.makeText(
                                                context,
                                                "标记已读失败: ${e.message}",
                                                Toast.LENGTH_SHORT,
                                            ).show()
                                        }
                                    }
                                },
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * 连接状态指示器
 *
 * 根据 [WebSocketConnectionState] 显示对应颜色的小圆点：
 * - Connected: 绿色
 * - Reconnecting: 橙色
 * - Disconnected/Failed: 灰色
 *
 * @param state 当前 WebSocket 连接状态
 */
@Composable
private fun ConnectionStateIndicator(state: WebSocketConnectionState) {
    val color = when (state) {
        is WebSocketConnectionState.Connected -> Color(0xFF4CAF50)
        is WebSocketConnectionState.Reconnecting -> Color(0xFFFF9800)
        is WebSocketConnectionState.Failed -> Color(0xFFF44336)
        WebSocketConnectionState.Disconnected -> Color(0xFF9E9E9E)
    }
    Box(
        modifier = Modifier
            .size(8.dp)
            .clip(CircleShape)
            .background(color),
    )
}

/**
 * 通知卡片
 *
 * 根据 [Notification.type] 显示对应图标，未读消息高亮背景。
 *
 * @param notification 通知数据
 * @param onClick 点击回调（用于标记已读）
 */
@Composable
private fun NotificationCard(
    notification: Notification,
    onClick: () -> Unit,
) {
    val icon = notificationTypeIcon(notification.type)
    val iconTint = if (!notification.read) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }

    Card(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(
            defaultElevation = if (!notification.read) 2.dp else 1.dp,
        ),
        colors = if (!notification.read) {
            CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
        } else {
            CardDefaults.cardColors()
        },
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // 类型图标
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = iconTint,
                )
            }
            Spacer(modifier = Modifier.padding(end = 12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = notification.title,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = if (!notification.read) FontWeight.SemiBold else FontWeight.Normal,
                    )
                    Text(
                        text = formatTime(notification.createdAt),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    text = notification.content,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                )
            }
            // 未读徽章
            if (!notification.read) {
                Spacer(modifier = Modifier.padding(start = 8.dp))
                Badge { Text(text = "新") }
            }
        }
    }
}

/**
 * 根据通知类型返回对应图标
 *
 * @param type 通知类型字符串（[NotificationType.value]）
 * @return Material 图标向量
 */
private fun notificationTypeIcon(type: String): ImageVector = when (type) {
    NotificationType.CHAT.value -> Icons.Outlined.Notifications
    NotificationType.APPROVAL.value -> Icons.Outlined.CheckCircle
    NotificationType.TASK_RESULT.value -> Icons.Outlined.TaskAlt
    NotificationType.SYSTEM.value -> Icons.Outlined.ErrorOutline
    NotificationType.BILLING.value -> Icons.Outlined.Bolt
    else -> Icons.Outlined.Notifications
}

/**
 * 格式化时间显示
 *
 * 后端返回 ISO 时间字符串（如 `2026-07-09T10:30:00+00:00`），
 * 这里简化为显示原始字符串的前 16 个字符（`2026-07-09 10:30`）。
 *
 * @param createdAt ISO 时间字符串
 * @return 格式化后的时间显示
 */
private fun formatTime(createdAt: String): String {
    if (createdAt.isBlank()) return ""
    return createdAt
        .replace("T", " ")
        .take(16)
}
