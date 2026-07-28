package com.xtys126.open_awa.features.scheduled

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.data.ScheduledTaskRepository
import com.xtys126.open_awa.data.model.CreateScheduledTaskRequest
import com.xtys126.open_awa.data.model.ScheduledTask
import com.xtys126.open_awa.data.model.ScheduledTaskExecution
import kotlinx.coroutines.launch

/**
 * 定时任务页
 *
 * 功能列表：
 * 1. 拉取用户的所有定时任务（[ScheduledTaskRepository.listTasks]）
 * 2. 状态徽章展示：pending / running / completed / failed / cancelled
 * 3. 点击任务卡片展开执行历史（[ScheduledTaskRepository.listExecutions]）
 * 4. 手动触发按钮（[ScheduledTaskRepository.triggerTask]）
 * 5. 取消按钮（[ScheduledTaskRepository.cancelTask]）
 * 6. 创建表单（标题 + prompt + 调度时间 + 是否每日）
 *
 * 数据流：
 * - 进入页面时拉取任务列表
 * - 触发/取消后刷新列表
 * - 创建后刷新列表
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScheduledTaskScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val repository = remember { ScheduledTaskRepository() }

    val tasks = remember { mutableStateListOf<ScheduledTask>() }
    val executionsMap = remember { mutableStateOf<MutableMap<Int, List<ScheduledTaskExecution>>>(mutableMapOf()) }
    val expandedTaskIds = remember { mutableStateListOf<Int>() }

    var isLoading by remember { mutableStateOf(true) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var showCreateDialog by remember { mutableStateOf(false) }

    /**
     * 拉取任务列表
     */
    fun loadTasks() {
        isLoading = true
        errorMessage = null
        scope.launch {
            runCatching {
                repository.listTasks()
            }.onSuccess { list ->
                tasks.clear()
                tasks.addAll(list)
                isLoading = false
            }.onFailure { e ->
                errorMessage = e.message ?: "拉取任务失败"
                isLoading = false
            }
        }
    }

    // 进入页面时拉取一次
    LaunchedEffect(Unit) {
        loadTasks()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = "定时任务", style = MaterialTheme.typography.titleMedium) },
                actions = {
                    IconButton(onClick = { loadTasks() }) {
                        Icon(
                            imageVector = Icons.Outlined.Refresh,
                            contentDescription = "刷新",
                        )
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { showCreateDialog = true }) {
                Icon(
                    imageVector = Icons.Outlined.Add,
                    contentDescription = "创建任务",
                )
            }
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            when {
                isLoading -> {
                    CircularProgressIndicator(
                        modifier = Modifier.align(Alignment.Center),
                    )
                }

                tasks.isEmpty() -> {
                    Text(
                        text = errorMessage ?: "暂无定时任务",
                        modifier = Modifier.align(Alignment.Center),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }

                else -> {
                    LazyColumn(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(horizontal = 16.dp, vertical = 8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        items(tasks, key = { it.id }) { task ->
                            val expanded = expandedTaskIds.contains(task.id)
                            TaskCard(
                                task = task,
                                expanded = expanded,
                                executions = executionsMap.value[task.id] ?: emptyList(),
                                onToggleExpand = {
                                    if (expanded) {
                                        expandedTaskIds.remove(task.id)
                                    } else {
                                        expandedTaskIds.add(task.id)
                                        // 展开时拉取执行历史
                                        scope.launch {
                                            runCatching {
                                                repository.listExecutions(taskId = task.id)
                                            }.onSuccess { list ->
                                                executionsMap.value = executionsMap.value.toMutableMap().apply {
                                                    this[task.id] = list
                                                }
                                            }.onFailure { e ->
                                                Toast.makeText(
                                                    context,
                                                    "拉取历史失败: ${e.message}",
                                                    Toast.LENGTH_SHORT,
                                                ).show()
                                            }
                                        }
                                    }
                                },
                                onTrigger = {
                                    scope.launch {
                                        runCatching {
                                            repository.triggerTask(task.id)
                                        }.onSuccess {
                                            Toast.makeText(context, "已触发任务", Toast.LENGTH_SHORT).show()
                                            loadTasks()
                                        }.onFailure { e ->
                                            Toast.makeText(
                                                context,
                                                "触发失败: ${e.message}",
                                                Toast.LENGTH_SHORT,
                                            ).show()
                                        }
                                    }
                                },
                                onCancel = {
                                    scope.launch {
                                        runCatching {
                                            repository.cancelTask(task.id)
                                        }.onSuccess {
                                            Toast.makeText(context, "已取消任务", Toast.LENGTH_SHORT).show()
                                            loadTasks()
                                        }.onFailure { e ->
                                            Toast.makeText(
                                                context,
                                                "取消失败: ${e.message}",
                                                Toast.LENGTH_SHORT,
                                            ).show()
                                        }
                                    }
                                },
                            )
                        }
                    }
                }
            }
        }
    }

    // 创建任务对话框
    if (showCreateDialog) {
        CreateTaskDialog(
            onDismiss = { showCreateDialog = false },
            onCreate = { request ->
                scope.launch {
                    runCatching {
                        repository.createTask(request)
                    }.onSuccess {
                        Toast.makeText(context, "任务已创建", Toast.LENGTH_SHORT).show()
                        showCreateDialog = false
                        loadTasks()
                    }.onFailure { e ->
                        Toast.makeText(
                            context,
                            "创建失败: ${e.message}",
                            Toast.LENGTH_SHORT,
                        ).show()
                    }
                }
            },
        )
    }
}

/**
 * 任务卡片
 *
 * 展示任务标题、状态徽章、调度时间、下次执行时间。
 * 展开后显示执行历史与操作按钮（触发 / 取消）。
 *
 * @param task 任务数据
 * @param expanded 是否展开
 * @param executions 执行历史
 * @param onToggleExpand 切换展开回调
 * @param onTrigger 手动触发回调
 * @param onCancel 取消任务回调
 */
@Composable
private fun TaskCard(
    task: ScheduledTask,
    expanded: Boolean,
    executions: List<ScheduledTaskExecution>,
    onToggleExpand: () -> Unit,
    onTrigger: () -> Unit,
    onCancel: () -> Unit,
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(
                    modifier = Modifier
                        .size(40.dp)
                        .clip(CircleShape)
                        .background(MaterialTheme.colorScheme.primaryContainer),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = Icons.Outlined.Schedule,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.onPrimaryContainer,
                    )
                }
                Spacer(modifier = Modifier.padding(end = 12.dp))
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = task.title,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = "调度: ${task.scheduledAt.take(16).replace("T", " ")}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                StatusBadge(status = task.status)
                IconButton(onClick = onToggleExpand) {
                    Icon(
                        imageVector = Icons.Outlined.ExpandMore,
                        contentDescription = if (expanded) "收起" else "展开",
                    )
                }
            }

            // 下次执行时间（仅 pending/running 状态显示）
            if (!task.nextExecutionAt.isNullOrBlank() &&
                (task.status == "pending" || task.status == "running")
            ) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "下次执行: ${task.nextExecutionAt!!.take(16).replace("T", " ")}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary,
                )
            }

            // 错误信息（仅 failed 状态显示）
            if (task.status == "failed" && !task.lastErrorMessage.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "错误: ${task.lastErrorMessage}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }

            // prompt 预览
            if (task.prompt.isNotBlank()) {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = task.prompt.take(120) + if (task.prompt.length > 120) "..." else "",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                )
            }

            // 展开内容：执行历史 + 操作按钮
            if (expanded) {
                Spacer(modifier = Modifier.height(12.dp))
                HorizontalDivider()
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "执行历史",
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Medium,
                )
                Spacer(modifier = Modifier.height(8.dp))
                if (executions.isEmpty()) {
                    Text(
                        text = "暂无执行记录",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    executions.take(5).forEach { execution ->
                        ExecutionItem(execution = execution)
                        Spacer(modifier = Modifier.height(6.dp))
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.End,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // 仅 pending / failed 状态允许触发
                    if (task.status == "pending" || task.status == "failed") {
                        OutlinedButton(
                            onClick = onTrigger,
                            modifier = Modifier.padding(end = 8.dp),
                        ) {
                            Icon(
                                imageVector = Icons.Outlined.PlayArrow,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp),
                            )
                            Spacer(modifier = Modifier.padding(end = 4.dp))
                            Text(text = "触发")
                        }
                    }
                    // 仅 pending / running 状态允许取消
                    if (task.status == "pending" || task.status == "running") {
                        OutlinedButton(onClick = onCancel) {
                            Icon(
                                imageVector = Icons.Outlined.Close,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp),
                            )
                            Spacer(modifier = Modifier.padding(end = 4.dp))
                            Text(text = "取消")
                        }
                    }
                }
            }
        }
    }
}

/**
 * 执行历史项
 *
 * @param execution 执行记录
 */
@Composable
private fun ExecutionItem(execution: ScheduledTaskExecution) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = RoundedCornerShape(6.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(modifier = Modifier.padding(8.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = execution.scheduledFor.take(16).replace("T", " "),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f),
                )
                StatusBadge(status = execution.status)
            }
            if (!execution.response.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = execution.response.take(80) + if (execution.response.length > 80) "..." else "",
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 2,
                )
            }
            if (!execution.errorMessage.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "错误: ${execution.errorMessage}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.error,
                    maxLines = 2,
                )
            }
        }
    }
}

/**
 * 状态徽章
 *
 * 根据 [status] 显示对应颜色：
 * - pending: 灰色
 * - running: 蓝色
 * - completed: 绿色
 * - failed: 红色
 * - cancelled: 橙色
 *
 * @param status 任务状态字符串
 */
@Composable
private fun StatusBadge(status: String) {
    val (label, color) = when (status) {
        "pending" -> "等待" to Color(0xFF94A3B8)
        "running" -> "运行中" to Color(0xFF3B82F6)
        "completed" -> "完成" to Color(0xFF10B981)
        "failed" -> "失败" to Color(0xFFEF4444)
        "cancelled" -> "已取消" to Color(0xFFF59E0B)
        else -> status to Color(0xFF94A3B8)
    }
    Surface(
        color = color.copy(alpha = 0.15f),
        contentColor = color,
        shape = MaterialTheme.shapes.small,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
        )
    }
}

/**
 * 创建任务对话框
 *
 * 表单字段：
 * - 标题（必填）
 * - 提示词（必填）
 * - 调度时间（ISO 字符串，如 `2026-07-09T18:30:00`，必填）
 * - 是否每日重复（开关，开启后调度时间作为每日执行时间）
 *
 * @param onDismiss 关闭回调
 * @param onCreate 创建回调，传入构建好的请求体
 */
@Composable
private fun CreateTaskDialog(
    onDismiss: () -> Unit,
    onCreate: (CreateScheduledTaskRequest) -> Unit,
) {
    var title by remember { mutableStateOf("") }
    var prompt by remember { mutableStateOf("") }
    var scheduledAt by remember { mutableStateOf("") }
    var isDaily by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(text = "创建定时任务") },
        text = {
            Column(modifier = Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it },
                    label = { Text(text = "任务标题") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = prompt,
                    onValueChange = { prompt = it },
                    label = { Text(text = "提示词") },
                    minLines = 3,
                    maxLines = 5,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(modifier = Modifier.height(8.dp))
                OutlinedTextField(
                    value = scheduledAt,
                    onValueChange = { scheduledAt = it },
                    label = { Text(text = "调度时间 (如 2026-07-09T18:30:00)") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(modifier = Modifier.height(8.dp))
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        text = "每日重复",
                        style = MaterialTheme.typography.bodyMedium,
                        modifier = Modifier.weight(1f),
                    )
                    Switch(checked = isDaily, onCheckedChange = { isDaily = it })
                }
                if (errorMessage != null) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = errorMessage!!,
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        },
        confirmButton = {
            Button(
                onClick = {
                    // 输入校验
                    if (title.isBlank()) {
                        errorMessage = "标题不能为空"
                        return@Button
                    }
                    if (prompt.isBlank()) {
                        errorMessage = "提示词不能为空"
                        return@Button
                    }
                    if (scheduledAt.isBlank()) {
                        errorMessage = "调度时间不能为空"
                        return@Button
                    }
                    errorMessage = null
                    val request = CreateScheduledTaskRequest(
                        title = title.trim(),
                        prompt = prompt.trim(),
                        scheduledAt = scheduledAt.trim(),
                        isDaily = isDaily,
                    )
                    onCreate(request)
                },
            ) {
                Text(text = "创建")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(text = "取消")
            }
        },
    )
}
