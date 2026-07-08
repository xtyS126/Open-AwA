package com.xtys126.open_awa.features.memory

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material3.Card
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.core.ui.StatusBadge

/**
 * 记忆页
 *
 * 三个 Tab：短期记忆 / 长期记忆 / 经验库
 * 右下角 FAB 添加记忆
 * 当前数据为 remember { mutableStateOf } 模拟，待 Repository 接入后替换
 */
@Composable
fun MemoryScreen() {
    var selectedTab by remember { mutableStateOf(0) }
    // TODO: 接入 MemoryRepository 加载记忆列表
    val memories by remember { mutableStateOf(sampleMemories()) }

    Box(modifier = Modifier.fillMaxSize()) {
        Column(modifier = Modifier.fillMaxSize()) {
            TabRow(selectedTabIndex = selectedTab) {
                Tab(
                    selected = selectedTab == 0,
                    onClick = { selectedTab = 0 },
                    text = { Text("短期记忆") },
                )
                Tab(
                    selected = selectedTab == 1,
                    onClick = { selectedTab = 1 },
                    text = { Text("长期记忆") },
                )
                Tab(
                    selected = selectedTab == 2,
                    onClick = { selectedTab = 2 },
                    text = { Text("经验库") },
                )
            }
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                items(memories) { memory ->
                    MemoryCard(memory)
                }
            }
        }
        FloatingActionButton(
            onClick = { /* TODO: 打开添加记忆对话框 */ },
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(16.dp),
        ) {
            Icon(
                imageVector = Icons.Outlined.Add,
                contentDescription = "添加记忆",
            )
        }
    }
}

/**
 * 记忆条目卡片
 */
@Composable
private fun MemoryCard(memory: MemoryItem) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = memory.time,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                StatusBadge(
                    text = memory.type.label,
                    color = memory.type.typeColor(),
                )
            }
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = memory.content,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

/**
 * 记忆类型枚举
 */
private enum class MemoryType(val label: String) {
    SHORT("短期"),
    LONG("长期"),
    EXPERIENCE("经验"),
}

/**
 * 记忆类型对应颜色
 * 短期-信息蓝、长期-紫、经验-成功绿
 */
private fun MemoryType.typeColor(): Color = when (this) {
    MemoryType.SHORT -> Color(0xFF3B82F6)
    MemoryType.LONG -> Color(0xFF8B5CF6)
    MemoryType.EXPERIENCE -> Color(0xFF10B981)
}

/**
 * 记忆条目数据模型
 */
private data class MemoryItem(
    val time: String,
    val content: String,
    val type: MemoryType,
)

private fun sampleMemories(): List<MemoryItem> = listOf(
    MemoryItem("14:32", "用户询问了 React 性能优化的方案", MemoryType.SHORT),
    MemoryItem("11:08", "用户偏好使用 TypeScript 进行开发", MemoryType.LONG),
    MemoryItem("昨天", "修复了 SSE 连接断开重连的问题", MemoryType.EXPERIENCE),
    MemoryItem("昨天", "用户正在开发 Open-AwA 项目", MemoryType.LONG),
    MemoryItem("2 天前", "Claude 模型在代码生成任务上表现更好", MemoryType.EXPERIENCE),
    MemoryItem("10:20", "用户提到了数据库连接池配置", MemoryType.SHORT),
)
