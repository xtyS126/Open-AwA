package com.xtys126.open_awa.features.inbox

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
import androidx.compose.material.icons.outlined.DoneAll
import androidx.compose.material.icons.outlined.MarkEmailUnread
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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * 收件箱页
 *
 * 通知消息中心：
 * - 顶部全部已读按钮
 * - 消息列表（发送者 + 摘要 + 时间 + 已读/未读徽章）
 *
 * TODO: 接入 InboxRepository 调用后端 /api/inbox/messages 接口
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun InboxScreen() {
    // 消息列表（模拟数据）
    var messages by remember {
        mutableStateOf(
            listOf(
                InboxMessage(
                    id = "1",
                    sender = "工作流引擎",
                    summary = "日报自动生成工作流执行完成，耗时 12s",
                    time = "2 分钟前",
                    read = false,
                ),
                InboxMessage(
                    id = "2",
                    sender = "子智能体：代码审查员",
                    summary = "发现 PR #42 中 3 处潜在 bug，请处理",
                    time = "10 分钟前",
                    read = false,
                ),
                InboxMessage(
                    id = "3",
                    sender = "计费系统",
                    summary = "本月预算已使用 78%，请注意控制",
                    time = "1 小时前",
                    read = true,
                ),
                InboxMessage(
                    id = "4",
                    sender = "插件管理器",
                    summary = "天气查询插件已成功更新到 v1.2.0",
                    time = "昨天",
                    read = true,
                ),
            ),
        )
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
                    }
                },
                actions = {
                    IconButton(onClick = {
                        // TODO: 调用 Repository.markAllRead 标记全部已读
                        messages = messages.map { it.copy(read = true) }
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
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(messages, key = { it.id }) { message ->
                InboxMessageCard(
                    message = message,
                    onClick = {
                        // TODO: 打开消息详情
                        messages = messages.map {
                            if (it.id == message.id) it.copy(read = true) else it
                        }
                    },
                )
            }
        }
    }
}

/**
 * 收件箱消息卡片
 */
@Composable
private fun InboxMessageCard(
    message: InboxMessage,
    onClick: () -> Unit,
) {
    Card(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = if (!message.read) 2.dp else 1.dp),
        colors = if (!message.read) {
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
            // 发送者头像（图标占位）
            Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.Outlined.MarkEmailUnread,
                    contentDescription = null,
                    tint = if (!message.read) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
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
                        text = message.sender,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = if (!message.read) FontWeight.SemiBold else FontWeight.Normal,
                    )
                    Text(
                        text = message.time,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    text = message.summary,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                )
            }
            // 未读徽章
            if (!message.read) {
                Spacer(modifier = Modifier.padding(start = 8.dp))
                Badge { Text(text = "新") }
            }
        }
    }
}

/**
 * 收件箱消息数据模型
 */
private data class InboxMessage(
    val id: String,
    val sender: String,
    val summary: String,
    val time: String,
    val read: Boolean,
)
