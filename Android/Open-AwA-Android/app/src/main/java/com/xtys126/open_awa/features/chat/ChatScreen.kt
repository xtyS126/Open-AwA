package com.xtys126.open_awa.features.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Chat
import androidx.compose.material.icons.outlined.Send
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.core.ui.EmptyBox
import java.util.UUID

/**
 * 聊天页
 *
 * 三段式布局：
 * - 顶部 [LazyRow] 会话列表（横向滚动，支持新建对话）
 * - 中部 [LazyColumn] 消息列表（用户消息右对齐主色调，AI 消息左对齐 surface）
 * - 底部 [Scaffold] bottomBar：[OutlinedTextField] + 发送 [IconButton]
 *
 * 空状态：居中显示"开始新对话"按钮（[EmptyBox]）
 *
 * TODO: ChatRepository 由其他子代理并行实现，当前用 [remember] + [mutableStateOf] 模拟数据
 *       接入后替换为 ViewModel + StateFlow + Flow 收集
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen() {
    // TODO: 替换为 ChatRepository + ViewModel
    var conversations by remember {
        mutableStateOf(
            listOf(
                Conversation(id = "1", title = "新对话"),
            ),
        )
    }
    var activeConversationId by remember { mutableStateOf("1") }
    var messages by remember { mutableStateOf<List<Message>>(emptyList()) }
    var inputText by remember { mutableStateOf("") }

    val listState = rememberLazyListState()

    // 消息列表变化时滚动到底部
    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.lastIndex)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = "聊天",
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                },
            )
        },
        bottomBar = {
            ChatInputBar(
                text = inputText,
                onTextChange = { inputText = it },
                onSend = {
                    val content = inputText.trim()
                    if (content.isEmpty()) return@ChatInputBar
                    val userMsg = Message(
                        id = UUID.randomUUID().toString(),
                        role = MessageRole.USER,
                        content = content,
                    )
                    messages = messages + userMsg
                    inputText = ""
                    // TODO: 调用 ChatRepository.sendMessage(content) 接收 AI 回复
                    // 当前用模拟回复占位
                    val aiMsg = Message(
                        id = UUID.randomUUID().toString(),
                        role = MessageRole.ASSISTANT,
                        content = "（模拟回复）你发送了：$content",
                    )
                    messages = messages + aiMsg
                },
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
        ) {
            // 会话列表（横向滚动）
            ConversationRow(
                conversations = conversations,
                activeId = activeConversationId,
                onSelect = { activeConversationId = it.id },
                onNew = {
                    val newConv = Conversation(
                        id = UUID.randomUUID().toString(),
                        title = "新对话 ${conversations.size + 1}",
                    )
                    conversations = conversations + newConv
                    activeConversationId = newConv.id
                    messages = emptyList()
                },
            )

            // 消息列表 / 空状态
            if (messages.isEmpty()) {
                EmptyBox(
                    icon = Icons.Outlined.Chat,
                    title = "暂无消息",
                    actionText = "开始新对话",
                    onAction = {
                        val userMsg = Message(
                            id = UUID.randomUUID().toString(),
                            role = MessageRole.USER,
                            content = "你好",
                        )
                        messages = listOf(userMsg)
                        // TODO: 触发 ChatRepository.sendMessage
                    },
                )
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(16.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    items(messages, key = { it.id }) { msg ->
                        MessageBubble(message = msg)
                    }
                }
            }
        }
    }
}

/**
 * 输入栏（Scaffold bottomBar）
 */
@Composable
private fun ChatInputBar(
    text: String,
    onTextChange: (String) -> Unit,
    onSend: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface)
            .padding(12.dp)
            .imePadding(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        OutlinedTextField(
            value = text,
            onValueChange = onTextChange,
            placeholder = { Text(text = "输入消息…") },
            modifier = Modifier.weight(1f),
            maxLines = 4,
        )
        IconButton(
            onClick = onSend,
            enabled = text.isNotBlank(),
        ) {
            Icon(
                imageVector = Icons.Outlined.Send,
                contentDescription = "发送",
                tint = if (text.isNotBlank()) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
        }
    }
}

/**
 * 会话列表（横向滚动）
 */
@Composable
private fun ConversationRow(
    conversations: List<Conversation>,
    activeId: String,
    onSelect: (Conversation) -> Unit,
    onNew: () -> Unit,
) {
    LazyRow(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            IconButton(onClick = onNew) {
                Icon(
                    imageVector = Icons.Outlined.Add,
                    contentDescription = "新建对话",
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
        }
        items(conversations, key = { it.id }) { conv ->
            val isActive = conv.id == activeId
            Box(
                modifier = Modifier
                    .background(
                        color = if (isActive) {
                            MaterialTheme.colorScheme.primaryContainer
                        } else {
                            MaterialTheme.colorScheme.surfaceVariant
                        },
                        shape = RoundedCornerShape(16.dp),
                    )
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Text(
                    text = conv.title,
                    style = MaterialTheme.typography.labelLarge,
                    color = if (isActive) {
                        MaterialTheme.colorScheme.onPrimaryContainer
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
        }
    }
}

/**
 * 消息气泡
 *
 * 用户消息右对齐 + 主色调背景，AI 消息左对齐 + surface 背景
 */
@Composable
private fun MessageBubble(message: Message) {
    val isUser = message.role == MessageRole.USER
    val alignment = if (isUser) Alignment.End else Alignment.Start
    val bgColor = if (isUser) {
        MaterialTheme.colorScheme.primary
    } else {
        MaterialTheme.colorScheme.surfaceVariant
    }
    val fgColor = if (isUser) {
        MaterialTheme.colorScheme.onPrimary
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }

    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = alignment,
    ) {
        Box(
            modifier = Modifier
                .background(
                    color = bgColor,
                    shape = RoundedCornerShape(12.dp),
                )
                .padding(horizontal = 12.dp, vertical = 8.dp),
        ) {
            Text(
                text = message.content,
                style = MaterialTheme.typography.bodyMedium,
                color = fgColor,
            )
        }
    }
}

// 数据类（TODO: 迁移到 data 层 ChatRepository）

private enum class MessageRole { USER, ASSISTANT }

private data class Message(
    val id: String,
    val role: MessageRole,
    val content: String,
)

private data class Conversation(
    val id: String,
    val title: String,
)
