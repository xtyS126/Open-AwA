package com.xtys126.open_awa.features.workflow

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
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Engineering
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * 工作流页
 *
 * 管理自定义工作流：
 * - 顶部 FAB 新建工作流
 * - 工作流卡片列表（名称 + 节点数 + 状态 + 运行按钮）
 *
 * TODO: 接入 WorkflowRepository 调用后端 /api/workflows CRUD 与 /api/workflows/run 接口
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkflowScreen() {
    // 工作流列表（模拟数据）
    var workflows by remember {
        mutableStateOf(
            listOf(
                WorkflowItem(
                    id = "1",
                    name = "日报自动生成",
                    nodeCount = 5,
                    status = WorkflowStatus.IDLE,
                ),
                WorkflowItem(
                    id = "2",
                    name = "代码 Review 流程",
                    nodeCount = 8,
                    status = WorkflowStatus.RUNNING,
                ),
                WorkflowItem(
                    id = "3",
                    name = "数据清洗管道",
                    nodeCount = 12,
                    status = WorkflowStatus.ERROR,
                ),
            ),
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = "工作流", style = MaterialTheme.typography.titleMedium) },
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = {
                    // TODO: 打开新建工作流编辑器
                    val newId = (workflows.size + 1).toString()
                    workflows = workflows + WorkflowItem(
                        id = newId,
                        name = "新建工作流 $newId",
                        nodeCount = 1,
                        status = WorkflowStatus.IDLE,
                    )
                },
                icon = { Icon(imageVector = Icons.Outlined.Add, contentDescription = null) },
                text = { Text(text = "新建工作流") },
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
            items(workflows, key = { it.id }) { workflow ->
                WorkflowCard(
                    workflow = workflow,
                    onRun = {
                        // TODO: 调用 Repository.runWorkflow 启动工作流
                        workflows = workflows.map {
                            if (it.id == workflow.id) it.copy(status = WorkflowStatus.RUNNING) else it
                        }
                    },
                )
            }
        }
    }
}

/**
 * 工作流卡片
 */
@Composable
private fun WorkflowCard(
    workflow: WorkflowItem,
    onRun: () -> Unit,
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
                imageVector = Icons.Outlined.Engineering,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(32.dp),
            )
            Spacer(modifier = Modifier.padding(end = 12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = workflow.name,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = "节点数: ${workflow.nodeCount}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                // 状态徽章
                AssistChip(
                    onClick = {},
                    label = {
                        Text(
                            text = workflowStatusText(workflow.status),
                            style = MaterialTheme.typography.labelSmall,
                        )
                    },
                    colors = when (workflow.status) {
                        WorkflowStatus.RUNNING -> AssistChipDefaults.assistChipColors(
                            containerColor = MaterialTheme.colorScheme.primaryContainer,
                            labelColor = MaterialTheme.colorScheme.onPrimaryContainer,
                        )
                        WorkflowStatus.ERROR -> AssistChipDefaults.assistChipColors(
                            containerColor = MaterialTheme.colorScheme.errorContainer,
                            labelColor = MaterialTheme.colorScheme.onErrorContainer,
                        )
                        WorkflowStatus.IDLE -> AssistChipDefaults.assistChipColors(
                            containerColor = MaterialTheme.colorScheme.surfaceVariant,
                            labelColor = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    },
                )
            }
            // 运行按钮
            IconButton(onClick = onRun, enabled = workflow.status != WorkflowStatus.RUNNING) {
                Icon(
                    imageVector = Icons.Outlined.PlayArrow,
                    contentDescription = "运行",
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

/**
 * 工作流状态枚举
 */
private enum class WorkflowStatus {
    IDLE,
    RUNNING,
    ERROR,
}

/**
 * 工作流状态文本
 */
private fun workflowStatusText(status: WorkflowStatus): String = when (status) {
    WorkflowStatus.IDLE -> "空闲"
    WorkflowStatus.RUNNING -> "运行中"
    WorkflowStatus.ERROR -> "异常"
}

/**
 * 工作流数据模型
 */
private data class WorkflowItem(
    val id: String,
    val name: String,
    val nodeCount: Int,
    val status: WorkflowStatus,
)
