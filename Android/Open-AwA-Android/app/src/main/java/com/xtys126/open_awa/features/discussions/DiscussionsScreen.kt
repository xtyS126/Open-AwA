package com.xtys126.open_awa.features.discussions

import androidx.compose.foundation.background
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
import androidx.compose.material.icons.outlined.Forum
import androidx.compose.material.icons.outlined.ThumbUp
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
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
 * 讨论页
 *
 * 多 Agent 协作讨论：
 * - 顶部筛选 Tab（进行中 / 已结束）
 * - 讨论任务卡片列表（标题 + 参与者 + 投票数）
 *
 * TODO: 接入 DiscussionRepository 调用后端 /api/discussions 列表接口
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DiscussionsScreen() {
    // Tab 索引：0=进行中，1=已结束
    var selectedTab by remember { mutableStateOf(0) }

    // 讨论列表（模拟数据）
    val allDiscussions = remember {
        listOf(
            DiscussionItem(
                id = "1",
                title = "如何优化 LLM 调用链路的延迟？",
                participants = listOf("Claude", "GPT-4", "Qwen"),
                votes = 12,
                active = true,
            ),
            DiscussionItem(
                id = "2",
                title = "Plugin 沙箱隔离方案对比",
                participants = listOf("Claude", "Codex"),
                votes = 8,
                active = true,
            ),
            DiscussionItem(
                id = "3",
                title = "v2.0 路线图讨论",
                participants = listOf("Claude", "GPT-4", "Qwen", "Codex"),
                votes = 24,
                active = false,
            ),
            DiscussionItem(
                id = "4",
                title = "前端组件库选型",
                participants = listOf("Claude"),
                votes = 5,
                active = false,
            ),
        )
    }

    // 当前 Tab 过滤后的列表
    val filteredDiscussions = remember(allDiscussions, selectedTab) {
        if (selectedTab == 0) allDiscussions.filter { it.active } else allDiscussions.filter { !it.active }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = "讨论", style = MaterialTheme.typography.titleMedium) },
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            TabRow(selectedTabIndex = selectedTab) {
                Tab(
                    selected = selectedTab == 0,
                    onClick = { selectedTab = 0 },
                    text = { Text(text = "进行中") },
                )
                Tab(
                    selected = selectedTab == 1,
                    onClick = { selectedTab = 1 },
                    text = { Text(text = "已结束") },
                )
            }

            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(filteredDiscussions, key = { it.id }) { discussion ->
                    DiscussionCard(discussion = discussion)
                }
            }
        }
    }
}

/**
 * 讨论卡片
 */
@Composable
private fun DiscussionCard(discussion: DiscussionItem) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = Icons.Outlined.Forum,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(24.dp),
                )
                Spacer(modifier = Modifier.padding(end = 8.dp))
                Text(
                    text = discussion.title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
            }
            // 参与者头像列表（用首字母圆形占位）
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "参与者:",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(modifier = Modifier.padding(end = 8.dp))
                discussion.participants.forEach { participant ->
                    ParticipantAvatar(name = participant)
                    Spacer(modifier = Modifier.padding(end = 4.dp))
                }
            }
            // 投票数
            Row(
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = Icons.Outlined.ThumbUp,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.secondary,
                    modifier = Modifier.size(16.dp),
                )
                Spacer(modifier = Modifier.padding(end = 4.dp))
                Text(
                    text = "${discussion.votes} 票",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/**
 * 参与者头像（首字母圆形占位）
 */
@Composable
private fun ParticipantAvatar(name: String) {
    val initial = name.firstOrNull()?.uppercase() ?: "?"
    androidx.compose.foundation.layout.Box(
        modifier = Modifier
            .size(24.dp)
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.primary),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = initial,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onPrimary,
            fontWeight = FontWeight.Bold,
        )
    }
}

/**
 * 讨论数据模型
 */
private data class DiscussionItem(
    val id: String,
    val title: String,
    val participants: List<String>,
    val votes: Int,
    val active: Boolean,
)
