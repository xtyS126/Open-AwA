package com.xtys126.open_awa.features.vibecoding

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Build
import androidx.compose.material.icons.outlined.ExpandLess
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.Send
import androidx.compose.material.icons.outlined.Stop
import androidx.compose.material.icons.outlined.Terminal
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.data.AcpAgent
import com.xtys126.open_awa.data.AcpEvent
import com.xtys126.open_awa.data.AcpRepository
import com.xtys126.open_awa.data.AcpSession
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/**
 * Vibe Coding 页
 *
 * 通过 ACP 协议拉起后端注册的 CLI Agent（claude_code/codex/openclaw/opencode），
 * 所有 Agent 进程在服务器后端运行，Android 端通过 SSE 接收事件流。
 *
 * 移动端三栏布局（适配窄屏）：
 * 1. 顶部 Agent 选择区（横向滚动卡片，点击切换会话）
 * 2. 中间会话区（消息流 + 输入框 + 发送/取消按钮）
 * 3. 底部工具调用事件流（可折叠，展示 tool 事件列表）
 *
 * 流式 UI 处理 AcpEvent：
 * - text: 追加到当前 AI 消息
 * - tool: 添加到工具调用事件列表
 * - permission: 弹出审批对话框
 * - result: 标记本轮结束
 * - error: 显示错误提示
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VibeCodingScreen() {
    val repository = remember { AcpRepository() }
    val scope = rememberCoroutineScope()
    val snackbarHostState = remember { SnackbarHostState() }

    // 数据状态
    val agents = remember { mutableStateListOf<AcpAgent>() }
    val messages = remember { mutableStateListOf<VibeMessage>() }
    val toolEvents = remember { mutableStateListOf<AcpEvent>() }

    var selectedAgentId by remember { mutableStateOf<String?>(null) }
    var currentSession by remember { mutableStateOf<AcpSession?>(null) }
    var messageInput by remember { mutableStateOf("") }
    var isStreaming by remember { mutableStateOf(false) }
    var pendingPermission by remember { mutableStateOf<AcpEvent?>(null) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var showToolPanel by remember { mutableStateOf(false) }
    var isLoadingAgents by remember { mutableStateOf(false) }
    var streamJob by remember { mutableStateOf<Job?>(null) }

    // 初始化加载 Agent 列表
    LaunchedEffect(Unit) {
        isLoadingAgents = true
        try {
            val list = repository.listAgents()
            agents.clear()
            agents.addAll(list)
        } catch (e: Exception) {
            errorMessage = "加载 Agent 列表失败: ${e.message}"
        } finally {
            isLoadingAgents = false
        }
    }

    // 错误提示统一通过 Snackbar 展示
    LaunchedEffect(errorMessage) {
        errorMessage?.let {
            snackbarHostState.showSnackbar(it)
            errorMessage = null
        }
    }

    // 创建新会话（切换 Agent 时触发）
    fun createSession(agent: AcpAgent) {
        if (!agent.available) {
            errorMessage = "${agent.name} 未在服务器安装，无法启动"
            return
        }
        scope.launch {
            try {
                val session = repository.createSession(agent.id)
                currentSession = session
                selectedAgentId = agent.id
                messages.clear()
                toolEvents.clear()
                messages.add(
                    VibeMessage(
                        role = "agent",
                        content = "已创建 ${agent.name} 会话，请描述你的编码任务。",
                    ),
                )
            } catch (e: Exception) {
                errorMessage = "创建会话失败: ${e.message}"
            }
        }
    }

    // 发送 prompt 并订阅 SSE 事件流
    fun sendPrompt() {
        val session = currentSession
        val text = messageInput.trim()
        if (session == null || text.isBlank() || isStreaming) return

        messages.add(VibeMessage(role = "user", content = text))
        messageInput = ""

        // 占位的 AI 消息，用于流式追加文本
        val aiMessageIdx = messages.size
        messages.add(VibeMessage(role = "agent", content = ""))

        isStreaming = true
        streamJob = scope.launch {
            try {
                repository.streamPrompt(session.sessionId, text).collect { event ->
                    when (event.sseType) {
                        "text" -> {
                            // 追加文本到当前 AI 消息
                            if (aiMessageIdx < messages.size) {
                                val current = messages[aiMessageIdx]
                                messages[aiMessageIdx] = current.copy(
                                    content = current.content + event.text,
                                )
                            }
                        }
                        "tool" -> {
                            // 工具调用事件追加到底部列表
                            toolEvents.add(event)
                            if (!showToolPanel) showToolPanel = true
                        }
                        "permission" -> {
                            // 弹出审批对话框
                            pendingPermission = event
                        }
                        "result" -> {
                            // 一轮结束
                            isStreaming = false
                            if (event.status == "permission_required") {
                                // 等待用户审批，不结束流式标志
                                // pendingPermission 已通过 permission 事件设置
                            }
                        }
                        "error" -> {
                            errorMessage = event.message.ifBlank { "Agent 执行出错" }
                            isStreaming = false
                        }
                        else -> {
                            // status / usage 等事件暂不展示
                        }
                    }
                }
            } catch (e: Exception) {
                errorMessage = "流式请求失败: ${e.message}"
            } finally {
                isStreaming = false
            }
        }
    }

    // 取消当前轮次
    fun cancelTurn() {
        val session = currentSession ?: return
        streamJob?.cancel()
        scope.launch {
            try {
                repository.cancelTurn(session.sessionId)
            } catch (e: Exception) {
                errorMessage = "取消失败: ${e.message}"
            } finally {
                isStreaming = false
            }
        }
    }

    // 响应权限审批
    fun resolvePermission(optionId: String) {
        val session = currentSession ?: return
        scope.launch {
            try {
                repository.resolvePermission(session.sessionId, optionId)
                pendingPermission = null
            } catch (e: Exception) {
                errorMessage = "审批失败: ${e.message}"
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    val title = currentSession?.agent?.let { "$it 会话" } ?: "Vibe Coding"
                    Text(text = title, style = MaterialTheme.typography.titleMedium)
                },
                actions = {
                    if (isStreaming) {
                        IconButton(onClick = { cancelTurn() }) {
                            Icon(
                                imageVector = Icons.Outlined.Stop,
                                contentDescription = "取消当前轮次",
                                tint = MaterialTheme.colorScheme.error,
                            )
                        }
                    }
                    IconButton(onClick = { showToolPanel = !showToolPanel }) {
                        BadgedBox(
                            badge = {
                                if (toolEvents.isNotEmpty()) {
                                    Badge { Text(text = "${toolEvents.size}") }
                                }
                            },
                        ) {
                            Icon(
                                imageVector = if (showToolPanel) {
                                    Icons.Outlined.ExpandLess
                                } else {
                                    Icons.Outlined.ExpandMore
                                },
                                contentDescription = "工具调用事件",
                            )
                        }
                    }
                },
            )
        },
        snackbarHost = { SnackbarHost(hostState = snackbarHostState) },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            // 第一栏：Agent 选择区（横向滚动卡片）
            AgentSelectionRow(
                agents = agents,
                selectedAgentId = selectedAgentId,
                isLoading = isLoadingAgents,
                onSelect = { agent ->
                    if (agent.id != selectedAgentId) createSession(agent)
                },
                modifier = Modifier.fillMaxWidth(),
            )

            // 第二栏：会话区（消息流 + 输入框）
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
            ) {
                LazyColumn(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(messages) { msg ->
                        MessageBubble(message = msg)
                    }
                    if (isStreaming) {
                        item {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.Center,
                            ) {
                                CircularProgressIndicator(modifier = Modifier.size(16.dp))
                            }
                        }
                    }
                }

                // 输入框 + 发送按钮
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    OutlinedTextField(
                        value = messageInput,
                        onValueChange = { messageInput = it },
                        modifier = Modifier.weight(1f),
                        placeholder = {
                            val hint = if (currentSession == null) {
                                "请先选择 Agent"
                            } else {
                                "输入指令..."
                            }
                            Text(text = hint)
                        },
                        enabled = currentSession != null && !isStreaming,
                        singleLine = true,
                    )
                    Spacer(modifier = Modifier.size(8.dp))
                    IconButton(
                        onClick = { sendPrompt() },
                        enabled = currentSession != null && !isStreaming && messageInput.isNotBlank(),
                    ) {
                        Icon(
                            imageVector = Icons.Outlined.Send,
                            contentDescription = "发送",
                            tint = MaterialTheme.colorScheme.primary,
                        )
                    }
                }
            }

            // 第三栏：工具调用事件流（可折叠）
            AnimatedVisibility(visible = showToolPanel) {
                ToolEventsPane(
                    events = toolEvents,
                    modifier = Modifier
                        .fillMaxWidth()
                        .heightIn(max = 220.dp),
                )
            }
        }
    }

    // 权限审批对话框
    pendingPermission?.let { event ->
        PermissionDialog(
            event = event,
            onResolve = { optionId -> resolvePermission(optionId) },
            onDismiss = { pendingPermission = null },
        )
    }
}

/**
 * Agent 选择区（横向滚动卡片列表）
 */
@Composable
private fun AgentSelectionRow(
    agents: List<AcpAgent>,
    selectedAgentId: String?,
    isLoading: Boolean,
    onSelect: (AcpAgent) -> Unit,
    modifier: Modifier = Modifier,
) {
    if (isLoading) {
        Box(
            modifier = modifier.padding(16.dp),
            contentAlignment = Alignment.Center,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp))
                Spacer(modifier = Modifier.size(8.dp))
                Text(
                    text = "加载 Agent 列表...",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
        return
    }

    if (agents.isEmpty()) {
        Box(
            modifier = modifier.padding(16.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = "未发现可用 Agent，请在后端注册 ACP Agent",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        return
    }

    LazyRow(
        modifier = modifier,
        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(agents) { agent ->
            Card(
                onClick = { onSelect(agent) },
                modifier = Modifier.size(width = 140.dp, height = 72.dp),
                colors = if (agent.id == selectedAgentId) {
                    CardDefaults.cardColors(
                        containerColor = MaterialTheme.colorScheme.primaryContainer,
                    )
                } else {
                    CardDefaults.cardColors()
                },
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(
                        imageVector = Icons.Outlined.Terminal,
                        contentDescription = null,
                        tint = if (agent.available) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.outline
                        },
                    )
                    Spacer(modifier = Modifier.size(8.dp))
                    Column {
                        Text(
                            text = agent.name,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        Text(
                            text = if (agent.available) "可用" else "未安装",
                            style = MaterialTheme.typography.labelSmall,
                            color = if (agent.available) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.error
                            },
                        )
                    }
                }
            }
        }
    }
}

/**
 * 单条消息气泡
 */
@Composable
private fun MessageBubble(message: VibeMessage) {
    val isUser = message.role == "user"
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Card(
            modifier = Modifier.fillMaxWidth(0.85f),
            colors = if (isUser) {
                CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.primaryContainer,
                )
            } else {
                CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.surfaceVariant,
                )
            },
            shape = RoundedCornerShape(12.dp),
        ) {
            Column(modifier = Modifier.padding(12.dp)) {
                Text(
                    text = if (isUser) "用户" else "Agent",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(modifier = Modifier.size(4.dp))
                Text(
                    text = message.content,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
    }
}

/**
 * 工具调用事件流面板（可折叠）
 */
@Composable
private fun ToolEventsPane(
    events: List<AcpEvent>,
    modifier: Modifier = Modifier,
) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
        ),
    ) {
        Column(modifier = Modifier.padding(8.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = Icons.Outlined.Build,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(16.dp),
                )
                Spacer(modifier = Modifier.size(8.dp))
                Text(
                    text = "工具调用事件 (${events.size})",
                    style = MaterialTheme.typography.labelMedium,
                )
            }
            Spacer(modifier = Modifier.size(4.dp))
            LazyColumn(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                items(events) { event ->
                    ToolEventItem(event = event)
                }
            }
        }
    }
}

/**
 * 单条工具调用事件
 */
@Composable
private fun ToolEventItem(event: AcpEvent) {
    val name = event.name.ifBlank { event.title.ifBlank { event.toolName } }.ifBlank { "tool" }
    val status = event.status.ifBlank { event.kind }
    val summary = event.summary.ifBlank { event.detail }.ifBlank { event.target }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp),
        verticalAlignment = Alignment.Top,
    ) {
        Text(
            text = ">",
            style = MaterialTheme.typography.bodySmall,
            fontFamily = FontFamily.Monospace,
            color = MaterialTheme.colorScheme.primary,
            modifier = Modifier.padding(end = 6.dp),
        )
        Column(modifier = Modifier.fillMaxWidth()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = name,
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurface,
                )
                if (status.isNotBlank()) {
                    Spacer(modifier = Modifier.size(6.dp))
                    Text(
                        text = "[$status]",
                        style = MaterialTheme.typography.labelSmall,
                        color = when (status) {
                            "completed" -> MaterialTheme.colorScheme.primary
                            "failed" -> MaterialTheme.colorScheme.error
                            else -> MaterialTheme.colorScheme.onSurfaceVariant
                        },
                    )
                }
            }
            if (summary.isNotBlank()) {
                Text(
                    text = summary,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/**
 * 权限审批对话框
 *
 * 根据 permission 事件的 options 列表生成按钮，用户点击后通过
 * AcpRepository.resolvePermission 提交 option_id 恢复 Agent 执行。
 */
@Composable
private fun PermissionDialog(
    event: AcpEvent,
    onResolve: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(text = "权限审批请求") },
        text = {
            Column {
                val title = event.toolName.ifBlank { event.title }.ifBlank { "Agent 请求执行操作" }
                Text(text = title, style = MaterialTheme.typography.bodyMedium)
                if (event.detail.isNotBlank()) {
                    Spacer(modifier = Modifier.size(8.dp))
                    Text(
                        text = event.detail,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (event.target.isNotBlank()) {
                    Spacer(modifier = Modifier.size(4.dp))
                    Text(
                        text = "目标: ${event.target}",
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        },
        confirmButton = {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                event.options.forEach { option ->
                    TextButton(onClick = { onResolve(option.optionId) }) {
                        Text(text = option.name.ifBlank { option.kind }.ifBlank { "允许" })
                    }
                }
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(text = "取消")
            }
        },
    )
}

/**
 * 消息数据模型
 */
private data class VibeMessage(
    val role: String,
    val content: String,
)
