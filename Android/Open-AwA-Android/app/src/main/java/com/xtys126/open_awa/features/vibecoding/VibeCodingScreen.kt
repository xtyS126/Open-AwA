package com.xtys126.open_awa.features.vibecoding

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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Send
import androidx.compose.material.icons.outlined.Terminal
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp

/**
 * Vibe Coding 页
 *
 * 通过 ACP 协议拉起本地 CLI Agent（Claude Code / Codex / OpenClaw），
 * 移动端受屏幕宽度限制改为 TabRow 切换三栏：
 * - Tab 1: Agent 选择列表
 * - Tab 2: 会话面板（消息交互）
 * - Tab 3: 终端输出（PTY 流式回显）
 *
 * TODO: 接入 ACPHostedClient / AcpRepository 调用后端 /api/acp/sessions
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun VibeCodingScreen() {
    // Tab 索引：0=Agent 选择，1=会话面板，2=终端输出
    var selectedTab by remember { mutableStateOf(0) }

    // 当前选中的 Agent
    var selectedAgent by remember { mutableStateOf("Claude Code") }

    // 会话输入框
    var messageInput by remember { mutableStateOf("") }

    // 会话消息列表
    val messages = remember {
        mutableStateOf(
            listOf(
                MessageItem(role = "agent", content = "已就绪，请描述你的编码任务。"),
                MessageItem(role = "user", content = "帮我生成一个 Python 快速排序示例。"),
                MessageItem(role = "agent", content = "好的，正在生成 quicksort.py ..."),
            ),
        )
    }

    // 终端输出
    val terminalLines = remember {
        mutableStateOf(
            listOf(
                "[boot] claude-code agent started (pid=12876)",
                "[ready] workspace: D:/code/demo",
                "> claude '生成 quicksort.py'",
                "[edit] created quicksort.py (24 行)",
                "[done] exit code 0",
            ),
        )
    }

    // Agent 列表
    val agents = remember {
        listOf(
            AgentItem(name = "Claude Code", description = "Anthropic 官方 CLI Agent", available = true),
            AgentItem(name = "Codex", description = "OpenAI Codex CLI Agent", available = true),
            AgentItem(name = "OpenClaw", description = "开源 OpenClaw Agent", available = false),
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = "Vibe Coding", style = MaterialTheme.typography.titleMedium) },
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
                    text = { Text(text = "Agent") },
                )
                Tab(
                    selected = selectedTab == 1,
                    onClick = { selectedTab = 1 },
                    text = {
                        BadgedBox(badge = { Badge { Text(text = "${messages.value.size}") } }) {
                            Text(text = "会话")
                        }
                    },
                )
                Tab(
                    selected = selectedTab == 2,
                    onClick = { selectedTab = 2 },
                    text = { Text(text = "终端") },
                )
            }

            when (selectedTab) {
                0 -> AgentListPane(
                    agents = agents,
                    selectedAgent = selectedAgent,
                    onSelect = { selectedAgent = it },
                )

                1 -> SessionPane(
                    messages = messages.value,
                    input = messageInput,
                    onInputChange = { messageInput = it },
                    onSend = {
                        if (messageInput.isBlank()) return@SessionPane
                        // TODO: 调用 AcpRepository.runTurn 提交本轮 prompt
                        messages.value = messages.value + MessageItem(
                            role = "user",
                            content = messageInput,
                        )
                        messageInput = ""
                    },
                )

                2 -> TerminalPane(lines = terminalLines.value)
            }
        }
    }
}

/**
 * Agent 列表面板
 */
@Composable
private fun AgentListPane(
    agents: List<AgentItem>,
    selectedAgent: String,
    onSelect: (String) -> Unit,
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(agents) { agent ->
            Card(
                onClick = { if (agent.available) onSelect(agent.name) },
                enabled = agent.available,
                modifier = Modifier.fillMaxWidth(),
                colors = if (agent.name == selectedAgent) {
                    CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
                } else {
                    CardDefaults.cardColors()
                },
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(
                        modifier = Modifier.size(40.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            imageVector = Icons.Outlined.Terminal,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                        )
                    }
                    Spacer(modifier = Modifier.padding(end = 12.dp))
                    Column(modifier = Modifier.fillMaxWidth()) {
                        Text(
                            text = agent.name,
                            style = MaterialTheme.typography.titleMedium,
                        )
                        Text(
                            text = agent.description,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        if (!agent.available) {
                            Text(
                                text = "未安装",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.error,
                            )
                        }
                    }
                }
            }
        }
    }
}

/**
 * 会话面板
 */
@Composable
private fun SessionPane(
    messages: List<MessageItem>,
    input: String,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // 消息列表
        LazyColumn(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            items(messages) { msg ->
                MessageBubble(message = msg)
            }
        }
        Spacer(modifier = Modifier.size(0.dp))
        // 输入框
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value = input,
                onValueChange = onInputChange,
                modifier = Modifier.fillMaxWidth(),
                placeholder = { Text(text = "输入指令...") },
                singleLine = true,
            )
            IconButton(onClick = onSend) {
                Icon(
                    imageVector = Icons.Outlined.Send,
                    contentDescription = "发送",
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

/**
 * 单条消息气泡
 */
@Composable
private fun MessageBubble(message: MessageItem) {
    val isUser = message.role == "user"
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Card(
            modifier = Modifier
                .fillMaxWidth(0.8f),
            colors = if (isUser) {
                CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
            } else {
                CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
            },
            shape = CircleShape,
        ) {
            Column(modifier = Modifier.padding(12.dp)) {
                Text(
                    text = if (isUser) "用户" else "Agent",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = message.content,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
        }
    }
}

/**
 * 终端输出面板
 */
@Composable
private fun TerminalPane(lines: List<String>) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            lines.forEach { line ->
                Text(
                    text = line,
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}

/**
 * Agent 数据模型
 */
private data class AgentItem(
    val name: String,
    val description: String,
    val available: Boolean,
)

/**
 * 消息数据模型
 */
private data class MessageItem(
    val role: String,
    val content: String,
)
