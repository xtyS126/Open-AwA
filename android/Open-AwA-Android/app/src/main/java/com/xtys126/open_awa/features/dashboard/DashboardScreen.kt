package com.xtys126.open_awa.features.dashboard

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.Chat
import androidx.compose.material.icons.outlined.CreditCard
import androidx.compose.material.icons.outlined.Forum
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.core.ui.SectionHeader
import com.xtys126.open_awa.core.ui.StatCard

/**
 * 仪表盘页
 *
 * 展示用户使用概览：统计指标、最近活动、快捷操作
 * 当前数据为 remember { mutableStateOf } 模拟，待 Repository 接入后替换
 */
@Composable
fun DashboardScreen() {
    // TODO: 接入 DashboardRepository 加载真实统计数据
    val totalSessions by remember { mutableStateOf("128") }
    val todayMessages by remember { mutableStateOf("56") }
    val activeSkills by remember { mutableStateOf("12") }
    val monthlySpend by remember { mutableStateOf("¥ 32.50") }
    var activities by remember { mutableStateOf(sampleActivities()) }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { SectionHeader("概览") }
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                StatCard(
                    title = "总会话数",
                    value = totalSessions,
                    icon = Icons.Outlined.Chat,
                    modifier = Modifier.weight(1f),
                )
                StatCard(
                    title = "今日消息",
                    value = todayMessages,
                    icon = Icons.Outlined.Forum,
                    modifier = Modifier.weight(1f),
                )
            }
        }
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                StatCard(
                    title = "活跃技能",
                    value = activeSkills,
                    icon = Icons.Outlined.Bolt,
                    modifier = Modifier.weight(1f),
                )
                StatCard(
                    title = "本月消费",
                    value = monthlySpend,
                    icon = Icons.Outlined.CreditCard,
                    modifier = Modifier.weight(1f),
                )
            }
        }
        item { SectionHeader("最近活动") }
        items(activities) { activity ->
            ActivityCard(activity)
        }
        item { SectionHeader("快捷操作") }
        item { QuickActionsRow() }
        item { Spacer(modifier = Modifier.height(16.dp)) }
    }
}

/**
 * 活动卡片
 */
@Composable
private fun ActivityCard(activity: DashboardActivity) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = activity.icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(24.dp),
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = activity.title,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Medium,
                )
                Text(
                    text = activity.time,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/**
 * 快捷操作行
 *
 * 4 个等宽图标按钮：新对话 / 新技能 / 查看计费 / 设置
 */
@Composable
private fun QuickActionsRow() {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        QuickAction(label = "新对话", icon = Icons.Outlined.Add, modifier = Modifier.weight(1f))
        QuickAction(label = "新技能", icon = Icons.Outlined.Bolt, modifier = Modifier.weight(1f))
        QuickAction(label = "查看计费", icon = Icons.Outlined.CreditCard, modifier = Modifier.weight(1f))
        QuickAction(label = "设置", icon = Icons.Outlined.Settings, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun QuickAction(
    label: String,
    icon: ImageVector,
    modifier: Modifier = Modifier,
) {
    Card(modifier = modifier) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            IconButton(onClick = { /* TODO: 跳转到对应页面 */ }) {
                Icon(
                    imageVector = icon,
                    contentDescription = label,
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
            Text(
                text = label,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * 仪表盘活动数据模型
 */
private data class DashboardActivity(
    val title: String,
    val time: String,
    val icon: ImageVector,
)

/**
 * 模拟活动数据
 */
private fun sampleActivities(): List<DashboardActivity> = listOf(
    DashboardActivity("与 Claude 完成代码重构", "10 分钟前", Icons.Outlined.Chat),
    DashboardActivity("调用技能：网络搜索", "30 分钟前", Icons.Outlined.Bolt),
    DashboardActivity("扣费 ¥0.12 - GPT-4 调用", "1 小时前", Icons.Outlined.CreditCard),
    DashboardActivity("新建会话：需求评审", "2 小时前", Icons.Outlined.Add),
    DashboardActivity("更新插件配置", "昨天", Icons.Outlined.Settings),
)
