package com.xtys126.open_awa.features.im

import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
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
 * IM 渠道页
 *
 * 管理消息推送渠道：
 * - 渠道卡片列表（微信 / Slack / Discord / 飞书 / 钉钉）
 * - 启停开关（Switch）
 * - 状态徽章（已连接 / 未连接）
 * - 配置按钮
 *
 * TODO: 接入 ImChannelRepository 调用后端 /api/im/channels CRUD 接口
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ImChannelsScreen() {
    // 渠道列表（模拟数据）
    var channels by remember {
        mutableStateOf(
            listOf(
                ImChannel(id = "1", name = "微信", connected = true, enabled = true),
                ImChannel(id = "2", name = "Slack", connected = true, enabled = true),
                ImChannel(id = "3", name = "Discord", connected = false, enabled = false),
                ImChannel(id = "4", name = "飞书", connected = true, enabled = false),
                ImChannel(id = "5", name = "钉钉", connected = false, enabled = false),
            ),
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = "IM 渠道", style = MaterialTheme.typography.titleMedium) },
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
            items(channels, key = { it.id }) { channel ->
                ChannelCard(
                    channel = channel,
                    onToggle = { enabled ->
                        // TODO: 调用 Repository 更新渠道启用状态
                        channels = channels.map {
                            if (it.id == channel.id) it.copy(enabled = enabled) else it
                        }
                    },
                    onConfig = {
                        // TODO: 打开渠道配置对话框
                    },
                )
            }
        }
    }
}

/**
 * 渠道卡片
 */
@Composable
private fun ChannelCard(
    channel: ImChannel,
    onToggle: (Boolean) -> Unit,
    onConfig: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // 渠道图标（占位）
            androidx.compose.foundation.layout.Box(
                modifier = Modifier
                    .size(40.dp)
                    .clip(CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.Outlined.Notifications,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
            Spacer(modifier = Modifier.padding(end = 12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = channel.name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                // 状态徽章
                AssistChip(
                    onClick = {},
                    label = {
                        Text(
                            text = if (channel.connected) "已连接" else "未连接",
                            style = MaterialTheme.typography.labelSmall,
                        )
                    },
                    colors = if (channel.connected) {
                        AssistChipDefaults.assistChipColors(
                            containerColor = MaterialTheme.colorScheme.secondaryContainer,
                            labelColor = MaterialTheme.colorScheme.onSecondaryContainer,
                        )
                    } else {
                        AssistChipDefaults.assistChipColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant,
                            labelColor = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    },
                )
            }
            // 启停开关
            Switch(
                checked = channel.enabled,
                onCheckedChange = onToggle,
            )
            // 配置按钮
            IconButton(onClick = onConfig) {
                Icon(
                    imageVector = Icons.Outlined.Settings,
                    contentDescription = "配置",
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/**
 * IM 渠道数据模型
 */
private data class ImChannel(
    val id: String,
    val name: String,
    val connected: Boolean,
    val enabled: Boolean,
)
