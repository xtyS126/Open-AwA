package com.xtys126.open_awa.features.roles

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
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * 角色管理页
 *
 * 管理自定义角色：
 * - 顶部 FAB 新建角色
 * - 角色卡片列表（头像 + 名称 + 描述 + 编辑/删除）
 *
 * TODO: 接入 RoleRepository 调用后端 /api/roles CRUD 接口
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RolesScreen() {
    // 角色列表（模拟数据）
    var roles by remember {
        mutableStateOf(
            listOf(
                RoleItem(id = "1", name = "代码助手", description = "专注代码生成与重构", color = 0xFF3B82F6),
                RoleItem(id = "2", name = "翻译官", description = "中英互译，保持语义自然", color = 0xFF10B981),
                RoleItem(id = "3", name = "文档撰写", description = "撰写技术文档与需求规格", color = 0xFFF59E0B),
                RoleItem(id = "4", name = "数据分析师", description = "数据分析与可视化建议", color = 0xFF8B5CF6),
            ),
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = "角色管理", style = MaterialTheme.typography.titleMedium) },
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = {
                    // TODO: 打开新建角色对话框
                    val newId = (roles.size + 1).toString()
                    roles = roles + RoleItem(
                        id = newId,
                        name = "新角色 $newId",
                        description = "点击编辑修改描述",
                        color = 0xFFEF4444,
                    )
                },
                icon = { Icon(imageVector = Icons.Outlined.Add, contentDescription = null) },
                text = { Text(text = "新建角色") },
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
            items(roles, key = { it.id }) { role ->
                RoleCard(
                    role = role,
                    onEdit = {
                        // TODO: 打开编辑对话框
                    },
                    onDelete = {
                        // TODO: 调用 Repository 删除
                        roles = roles.filterNot { it.id == role.id }
                    },
                )
            }
        }
    }
}

/**
 * 角色卡片
 */
@Composable
private fun RoleCard(
    role: RoleItem,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
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
                    .size(48.dp)
                    .clip(CircleShape)
                    .background(Color(role.color)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.Outlined.Person,
                    contentDescription = null,
                    tint = Color.White,
                )
            }
            Spacer(modifier = Modifier.padding(end = 12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = role.name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = role.description,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Row {
                IconButton(onClick = onEdit) {
                    Icon(
                        imageVector = Icons.Outlined.Edit,
                        contentDescription = "编辑",
                        tint = MaterialTheme.colorScheme.primary,
                    )
                }
                IconButton(onClick = onDelete) {
                    Icon(
                        imageVector = Icons.Outlined.Delete,
                        contentDescription = "删除",
                        tint = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }
    }
}

/**
 * 角色数据模型
 */
private data class RoleItem(
    val id: String,
    val name: String,
    val description: String,
    val color: Long,
)
