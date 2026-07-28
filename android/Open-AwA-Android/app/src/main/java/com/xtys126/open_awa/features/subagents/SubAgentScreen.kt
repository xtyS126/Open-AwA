package com.xtys126.open_awa.features.subagents

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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CallSplit
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * 子智能体页
 *
 * 管理子智能体实例：
 * - 子智能体卡片列表（名称 + 模型 + 状态 + 启停开关）
 *
 * TODO: 接入 SubAgentRepository 调用后端 /api/subagents CRUD 接口
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SubAgentScreen() {
    // 子智能体列表（模拟数据）
    var agents by remember {
        mutableStateOf(
            listOf(
                SubAgentItem(
                    id = "1",
                    name = "代码审查员",
                    model = "claude-sonnet-4.5",
                    enabled = true,
                    running = true,
                ),
                SubAgentItem(
                    id = "2",
                    name = "测试生成器",
                    model = "gpt-4-turbo",
                    enabled = true,
                    running = false,
                ),
                SubAgentItem(
                    id = "3",
                    name = "文档总结",
                    model = "qwen-max",
                    enabled = false,
                    running = false,
                ),
            ),
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = "子智能体", style = MaterialTheme.typography.titleMedium) },
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
            items(agents, key = { it.id }) { agent ->
                SubAgentCard(
                    agent = agent,
                    onToggle = { enabled ->
                        // TODO: 调用 Repository 更新子智能体启用状态
                        agents = agents.map {
                            if (it.id == agent.id) it.copy(enabled = enabled) else it
                        }
                    },
                )
            }
        }
    }
}

/**
 * 子智能体卡片
 */
@Composable
private fun SubAgentCard(
    agent: SubAgentItem,
    onToggle: (Boolean) -> Unit,
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
            Icon(
                imageVector = Icons.Outlined.CallSplit,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(32.dp),
            )
            Spacer(modifier = Modifier.padding(end = 12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = agent.name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = "模型: ${agent.model}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                // 运行状态徽章
                AssistChip(
                    onClick = {},
                    label = {
                        Text(
                            text = if (agent.running) "运行中" else "已停止",
                            style = MaterialTheme.typography.labelSmall,
                        )
                    },
                    colors = if (agent.running) {
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
                checked = agent.enabled,
                onCheckedChange = onToggle,
            )
        }
    }
}

/**
 * 子智能体数据模型
 */
private data class SubAgentItem(
    val id: String,
    val name: String,
    val model: String,
    val enabled: Boolean,
    val running: Boolean,
)
