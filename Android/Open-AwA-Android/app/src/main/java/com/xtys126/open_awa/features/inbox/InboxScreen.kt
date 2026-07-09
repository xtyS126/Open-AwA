package com.xtys126.open_awa.features.inbox

import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
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
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.core.backend.WebSocketConnectionState
import com.xtys126.open_awa.core.theme.LocalBrandGradient
import com.xtys126.open_awa.core.ui.EmptyBox
import com.xtys126.open_awa.core.ui.LoadingBox
import com.xtys126.open_awa.data.AuthRepository
import com.xtys126.open_awa.data.Notification
import com.xtys126.open_awa.data.NotificationRepository
import com.xtys126.open_awa.data.NotificationType
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** 轮询兜底间隔（毫秒），WebSocket 断线时每 30 秒拉取一次 inbox 列表 */
private const val POLL_INTERVAL_MS = 30_000L

/**
 * 收件箱页
 *
 * 接入实时通知：
 * 1. 启动时通过 REST 拉取历史 inbox 消息（[NotificationRepository.listMessages]）
 * 2. 同时建立 WebSocket 连接，实时接收推送（[NotificationRepository.start]）
 * 3. WebSocket 推送的新通知插入列表顶部，带未读标记
 * 4. 点击通知调用 [NotificationRepository.markAsRead] 更新已读状态
 * 5. 顶部全部已读按钮调用 [NotificationRepository.markAllRead]
 * 6. 30 秒轮询兜底：WebSocket 断线时通过 REST 拉取最新消息，避免漏推
 * 7. 收到 task_result 通知时震动反馈（[vibrate]）
 *
 * 鉴权约束：WebSocket token 通过 Sec-WebSocket-Protocol 子协议传递，
 * 由 [NotificationRepository.start] 内部封装，UI 不感知。
 *
 * 系统通知：[NotificationRepository] 构造时传入 applicationContext，
 * 收到 task_result 时由 [com.xtys126.open_awa.core.notification.SystemNotifier]
 * 弹出系统通知栏通知（即使 App 在后台也能看到）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun InboxScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    // Repository 实例（remember 保证跨 recompose 复用，避免重复创建）
    // 传入 applicationContext 以启用系统通知栏通知
    val notificationRepo = remember {
        NotificationRepository(appContext = context.applicationContext)
    }
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
                    // 收到 task_result 通知时震动反馈
                    if (notification.type == NotificationType.TASK_RESULT.value) {
                        vibrate(context)
                    }
                }
            }
        }.onFailure { e ->
            // WebSocket 启动失败不阻塞 UI，仅记录错误
            errorMessage = "实时通道启动失败: ${e.message}"
        }
    }

    // 30 秒轮询兜底：WebSocket 断线时通过 REST 拉取最新消息
    // 与 WebSocket 同时运行，作为补漏机制（不替代 WebSocket）
    LaunchedEffect(Unit) {
        while (true) {
            delay(POLL_INTERVAL_MS)
            runCatching {
                notificationRepo.listMessages()
            }.onSuccess { response ->
                // 仅在拉取到的最新消息 id 不在本地列表顶部时刷新
                // 避免覆盖 WebSocket 实时推送的顺序
                val topId = messages.firstOrNull()?.id
                val remoteTopId = response.messages.firstOrNull()?.id
                if (topId != remoteTopId) {
                    messages.clear()
                    messages.addAll(response.messages)
                }
            }.onFailure { e ->
                // 轮询失败不阻塞 UI，仅记录错误
                errorMessage = "轮询失败: ${e.message}"
            }
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
                    // 加载中：使用通用 LoadingBox（品牌色）
                    LoadingBox()
                }

                messages.isEmpty() -> {
                    // 空列表：使用通用 EmptyBox（品牌渐变图标）
                    EmptyBox(
                        icon = Icons.Outlined.Notifications,
                        title = errorMessage ?: "暂无通知",
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
 * 震动反馈
 *
 * 收到 task_result 通知时调用，短促震动 200ms 提醒用户。
 *
 * 兼容性：
 * - Android 8+（API 26+）：使用 [VibrationEffect.createOneShot]
 * - Android 7 及以下：使用废弃的 [Vibrator.vibrate]（无 VibrationEffect）
 *
 * @param context 任意 Context
 */
private fun vibrate(context: android.content.Context) {
    try {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            // Android 12+ 通过 VibratorManager 获取 Vibrator
            val vibratorManager = context.getSystemService(
                android.content.Context.VIBRATOR_MANAGER_SERVICE,
            ) as? VibratorManager
            val vibrator = vibratorManager?.defaultVibrator ?: return
            if (vibrator.hasVibrator()) {
                vibrator.vibrate(
                    VibrationEffect.createOneShot(
                        VIBRATION_DURATION_MS,
                        VibrationEffect.DEFAULT_AMPLITUDE,
                    ),
                )
            }
        } else {
            @Suppress("DEPRECATION")
            val vibrator = context.getSystemService(
                android.content.Context.VIBRATOR_SERVICE,
            ) as? Vibrator ?: return
            if (vibrator.hasVibrator()) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    vibrator.vibrate(
                        VibrationEffect.createOneShot(
                            VIBRATION_DURATION_MS,
                            VibrationEffect.DEFAULT_AMPLITUDE,
                        ),
                    )
                } else {
                    @Suppress("DEPRECATION")
                    vibrator.vibrate(VIBRATION_DURATION_MS)
                }
            }
        }
    } catch (e: Exception) {
        // 震动失败不阻塞主流程
        android.util.Log.w("InboxScreen", "震动反馈失败: ${e.message}", e)
    }
}

/** 震动时长（毫秒） */
private const val VIBRATION_DURATION_MS = 200L

/**
 * 连接状态指示器
 *
 * 根据 [WebSocketConnectionState] 显示对应颜色的小圆点 + 文字标签：
 * - Connected: 绿色 + "已连接"
 * - Reconnecting: 橙色 + "重连中"
 * - Failed: 红色 + "连接失败"
 * - Disconnected: 灰色 + "未连接"
 *
 * 2026-07-09 UI 优化：
 * - 双圈设计：外圈淡色背景 18dp + 内圈实色 8dp，更精致
 * - 增加文字标签，状态语义清晰
 * - 颜色改为半透明叠加，与主题更协调
 *
 * @param state 当前 WebSocket 连接状态
 */
@Composable
private fun ConnectionStateIndicator(state: WebSocketConnectionState) {
    val (color, label) = when (state) {
        is WebSocketConnectionState.Connected -> Color(0xFF22C55E) to "已连接"
        is WebSocketConnectionState.Reconnecting -> Color(0xFFF59E0B) to "重连中"
        is WebSocketConnectionState.Failed -> Color(0xFFEF4444) to "连接失败"
        WebSocketConnectionState.Disconnected -> Color(0xFF9CA3AF) to "未连接"
    }
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        // 双圈设计：外圈淡色背景 + 内圈实色
        Box(
            modifier = Modifier.size(18.dp),
            contentAlignment = Alignment.Center,
        ) {
            Box(
                modifier = Modifier
                    .size(18.dp)
                    .clip(CircleShape)
                    .background(color.copy(alpha = 0.18f)),
            )
            Box(
                modifier = Modifier
                    .size(8.dp)
                    .clip(CircleShape)
                    .background(color),
            )
        }
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * 通知卡片
 *
 * 根据 [Notification.type] 显示对应图标，未读消息高亮背景。
 *
 * 2026-07-09 UI 优化：
 * - 类型图标用品牌渐变圆形背景（未读）或 surfaceVariant 圆形背景（已读）
 * - 未读时左侧加品牌色竖条作为未读指示，替代右侧"新"Badge
 * - 圆角 16dp + 未读 elevation 2dp / 已读 0dp
 * - 标题/时间分两行排版，标题 SemiBold（未读） / Normal（已读）
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
    val isUnread = !notification.read

    Card(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        elevation = CardDefaults.cardElevation(
            defaultElevation = if (isUnread) 2.dp else 0.dp,
        ),
        colors = if (isUnread) {
            CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
        } else {
            CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
        },
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // 未读左侧竖条指示
            if (isUnread) {
                Box(
                    modifier = Modifier
                        .size(width = 3.dp, height = 36.dp)
                        .clip(RoundedCornerShape(2.dp))
                        .background(LocalBrandGradient.current),
                )
                Spacer(modifier = Modifier.size(10.dp))
            } else {
                Spacer(modifier = Modifier.size(13.dp))
            }

            // 类型图标：未读用品牌渐变圆形背景，已读用 surfaceVariant
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape)
                    .background(
                        if (isUnread) {
                            LocalBrandGradient.current
                        } else {
                            Brush.linearGradient(
                                listOf(
                                    MaterialTheme.colorScheme.surfaceVariant,
                                    MaterialTheme.colorScheme.surfaceVariant,
                                ),
                            )
                        },
                    ),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = if (isUnread) {
                        MaterialTheme.colorScheme.onPrimary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    modifier = Modifier.size(20.dp),
                )
            }
            Spacer(modifier = Modifier.size(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = notification.title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = if (isUnread) FontWeight.SemiBold else FontWeight.Normal,
                    color = if (isUnread) {
                        MaterialTheme.colorScheme.onPrimaryContainer
                    } else {
                        MaterialTheme.colorScheme.onSurface
                    },
                )
                Spacer(modifier = Modifier.size(2.dp))
                Text(
                    text = notification.content,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                )
                Spacer(modifier = Modifier.size(4.dp))
                Text(
                    text = formatTime(notification.createdAt),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
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
