package com.xtys126.open_awa.features.plugins

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Extension
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
 * 插件页
 *
 * 顶部搜索框 + 插件列表（名称、版本、状态徽章、配置按钮）
 * 当前数据为 remember { mutableStateOf } 模拟，待 Repository 接入后替换
 */
@Composable
fun PluginsScreen() {
    var query by remember { mutableStateOf("") }
    // TODO: 接入 PluginsRepository 加载插件列表
    val plugins by remember { mutableStateOf(samplePlugins()) }
    val filtered = remember(plugins, query) {
        if (query.isBlank()) {
            plugins
        } else {
            plugins.filter { it.name.contains(query, ignoreCase = true) }
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            placeholder = { Text("搜索插件") },
            leadingIcon = {
                Icon(
                    imageVector = Icons.Outlined.Search,
                    contentDescription = null,
                )
            },
            singleLine = true,
        )
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            items(filtered) { plugin ->
                PluginCard(plugin)
            }
        }
    }
}

/**
 * 插件卡片
 */
@Composable
private fun PluginCard(plugin: Plugin) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Outlined.Extension,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = plugin.name,
                        style = MaterialTheme.typography.bodyLarge,
                        fontWeight = FontWeight.Medium,
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                    StatusBadge(
                        text = plugin.status.label,
                        color = plugin.status.statusColor(),
                    )
                }
                Text(
                    text = "版本 ${plugin.version}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = { /* TODO: 打开插件配置页 */ }) {
                Icon(
                    imageVector = Icons.Outlined.Settings,
                    contentDescription = "配置",
                )
            }
        }
    }
}

/**
 * 插件状态枚举
 */
private enum class PluginStatus(val label: String) {
    RUNNING("运行中"),
    STOPPED("已停止"),
    ERROR("异常"),
}

/**
 * 插件状态对应颜色
 * 运行中-成功绿、已停止-中性灰、异常-错误红
 */
private fun PluginStatus.statusColor(): Color = when (this) {
    PluginStatus.RUNNING -> Color(0xFF10B981)
    PluginStatus.STOPPED -> Color(0xFF94A3B8)
    PluginStatus.ERROR -> Color(0xFFEF4444)
}

/**
 * 插件数据模型
 */
private data class Plugin(
    val name: String,
    val version: String,
    val status: PluginStatus,
)

private fun samplePlugins(): List<Plugin> = listOf(
    Plugin("天气查询", "1.2.0", PluginStatus.RUNNING),
    Plugin("股票数据", "0.9.3", PluginStatus.RUNNING),
    Plugin("地图导航", "2.0.1", PluginStatus.STOPPED),
    Plugin("短信通知", "1.0.0", PluginStatus.ERROR),
    Plugin("日历同步", "3.4.2", PluginStatus.RUNNING),
)
