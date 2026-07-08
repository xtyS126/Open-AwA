package com.xtys126.open_awa.features.user

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
import androidx.compose.material.icons.automirrored.outlined.Logout
import androidx.compose.material.icons.outlined.AccountCircle
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.Notifications
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * 用户中心页
 *
 * 个人中心：
 * - 顶部用户信息卡（头像 + 用户名 + 邮箱 + 编辑按钮）
 * - 统计行（会话数 / 技能数 / 经验数）
 * - 菜单列表（账户设置 / 通知 / 隐私 / 关于 / 退出登录）
 *
 * TODO: 接入 UserRepository 调用后端 /api/user/profile 接口
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UserCenterScreen() {
    // 用户信息（模拟数据）
    var user by remember {
        mutableStateOf(
            UserProfile(
                username = "Open-AwA 用户",
                email = "user@open-awa.local",
                avatarColor = 0xFF3B82F6,
            ),
        )
    }

    // 统计数据
    val stats = remember {
        listOf(
            StatItem(label = "会话", value = 28),
            StatItem(label = "技能", value = 12),
            StatItem(label = "经验", value = 47),
        )
    }

    // 菜单项
    val menuItems = remember {
        listOf(
            MenuItem(id = "account", title = "账户设置", icon = Icons.Outlined.AccountCircle),
            MenuItem(id = "notifications", title = "通知偏好", icon = Icons.Outlined.Notifications),
            MenuItem(id = "privacy", title = "隐私与安全", icon = Icons.Outlined.Lock),
            MenuItem(id = "about", title = "关于", icon = Icons.Outlined.Info),
            MenuItem(id = "logout", title = "退出登录", icon = Icons.AutoMirrored.Outlined.Logout),
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = "用户中心", style = MaterialTheme.typography.titleMedium) },
            )
        },
    ) { innerPadding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // 用户信息卡
            item {
                UserInfoCard(
                    user = user,
                    onEdit = {
                        // TODO: 打开编辑用户信息对话框
                    },
                )
            }

            // 统计行
            item {
                StatsRow(stats = stats)
            }

            // 菜单列表
            item {
                Text(
                    text = "设置",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 8.dp, bottom = 4.dp),
                )
            }
            items(menuItems, key = { it.id }) { menuItem ->
                MenuRow(item = menuItem) {
                    // TODO: 根据 menuItem.id 跳转对应页面
                }
            }
        }
    }
}

/**
 * 用户信息卡
 */
@Composable
private fun UserInfoCard(
    user: UserProfile,
    onEdit: () -> Unit,
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
            // 头像
            Box(
                modifier = Modifier
                    .size(64.dp)
                    .clip(CircleShape)
                    .background(Color(user.avatarColor)),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = user.username.firstOrNull()?.toString() ?: "U",
                    style = MaterialTheme.typography.headlineMedium,
                    color = Color.White,
                    fontWeight = FontWeight.Bold,
                )
            }
            Spacer(modifier = Modifier.padding(end = 16.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = user.username,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = user.email,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            IconButton(onClick = onEdit) {
                Icon(
                    imageVector = Icons.Outlined.Edit,
                    contentDescription = "编辑",
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

/**
 * 统计行
 */
@Composable
private fun StatsRow(stats: List<StatItem>) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = 16.dp),
            horizontalArrangement = Arrangement.SpaceEvenly,
        ) {
            stats.forEach { stat ->
                StatCell(label = stat.label, value = stat.value)
            }
        }
    }
}

/**
 * 统计单元格
 */
@Composable
private fun StatCell(label: String, value: Int) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            text = "$value",
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary,
        )
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

/**
 * 菜单行
 */
@Composable
private fun MenuRow(item: MenuItem, onClick: () -> Unit) {
    Card(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = item.icon,
                contentDescription = null,
                tint = if (item.id == "logout") {
                    MaterialTheme.colorScheme.error
                } else {
                    MaterialTheme.colorScheme.primary
                },
            )
            Spacer(modifier = Modifier.padding(end = 12.dp))
            Text(
                text = item.title,
                style = MaterialTheme.typography.bodyLarge,
                color = if (item.id == "logout") {
                    MaterialTheme.colorScheme.error
                } else {
                    MaterialTheme.colorScheme.onSurface
                },
                modifier = Modifier.weight(1f),
            )
            Icon(
                imageVector = Icons.Outlined.ChevronRight,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * 用户资料数据模型
 */
private data class UserProfile(
    val username: String,
    val email: String,
    val avatarColor: Long,
)

/**
 * 统计项数据模型
 */
private data class StatItem(
    val label: String,
    val value: Int,
)

/**
 * 菜单项数据模型
 */
private data class MenuItem(
    val id: String,
    val title: String,
    val icon: ImageVector,
)
