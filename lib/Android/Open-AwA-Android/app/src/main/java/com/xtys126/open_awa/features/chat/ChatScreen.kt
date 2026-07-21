package com.xtys126.open_awa.features.chat

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import android.util.Log
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.AttachFile
import androidx.compose.material.icons.outlined.Chat
import androidx.compose.material.icons.outlined.Send
import androidx.compose.material.icons.outlined.Stop
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.core.ui.EmptyBox
import com.xtys126.open_awa.data.ChatRepository
import com.xtys126.open_awa.data.model.AttachmentResponse
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import java.util.UUID

private const val TAG = "ChatScreen"

/**
 * 聊天页
 *
 * 三段式布局：
 * - 顶部 [LazyRow] 会话列表（横向滚动，支持新建对话）
 * - 中部 [LazyColumn] 消息列表（用户消息右对齐主色调，AI 消息左对齐 surface）
 * - 底部 [Scaffold] bottomBar：附件按钮 + [OutlinedTextField] + 发送/停止 [IconButton]
 *
 * 流式聊天：调用 [ChatRepository.streamMessage] 接收 SSE 增量文本，
 * AI 回复气泡实时追加 content；点击停止按钮取消协程，SSE 连接自动断开。
 *
 * 附件上传：点击附件按钮通过 [ActivityResultContracts.GetContent] 选文件，
 * 上传到 `/api/chat/upload` 后显示文件名缩略，随用户消息一起入列表。
 *
 * 当前会话列表为本地占位（避免依赖后端会话接口），activeConversationId 用作
 * 流式聊天的 session_id 传给后端；后续接入真实会话接口时替换即可。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen() {
    val repository = remember { ChatRepository() }
    val scope = rememberCoroutineScope()
    val context = LocalContext.current

    var conversations by remember {
        mutableStateOf(
            listOf(
                Conversation(id = "default", title = "默认会话"),
            ),
        )
    }
    var activeConversationId by remember { mutableStateOf("default") }
    val messages = remember { mutableStateListOf<UiMessage>() }
    var inputText by remember { mutableStateOf("") }
    val pendingAttachments = remember { mutableStateListOf<AttachmentResponse>() }
    var streamingJob by remember { mutableStateOf<Job?>(null) }
    var isStreaming by remember { mutableStateOf(false) }
    var isUploading by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }

    val listState = rememberLazyListState()

    // 消息列表变化时滚动到底部
    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.lastIndex)
        }
    }

    // 文件选择器：返回 Uri 后读取字节并上传
    val filePicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetContent(),
    ) { uri: Uri? ->
        if (uri == null) return@rememberLauncherForActivityResult
        scope.launch {
            isUploading = true
            try {
                val mimeType = context.contentResolver.getType(uri)
                    ?: "application/octet-stream"
                val fileName = queryFileName(context, uri) ?: "upload"
                val bytes = readUriBytes(context, uri)
                val response = repository.uploadAttachmentBytes(
                    bytes = bytes,
                    fileName = fileName,
                    mimeType = mimeType,
                )
                pendingAttachments.add(response)
            } catch (e: Exception) {
                Log.e(TAG, "附件上传失败: ${e.message}", e)
                errorMessage = "附件上传失败: ${e.message}"
            } finally {
                isUploading = false
            }
        }
    }

    /**
     * 发送消息：构造用户消息 + 空 AI 消息，启动 SSE 流协程实时追加 content
     */
    fun sendMessage(content: String) {
        if (content.isBlank() && pendingAttachments.isEmpty()) return
        if (isStreaming) return

        val userMsg = UiMessage(
            id = UUID.randomUUID().toString(),
            role = MessageRole.USER,
            content = content,
            attachments = pendingAttachments.toList(),
        )
        val aiMsg = UiMessage(
            id = UUID.randomUUID().toString(),
            role = MessageRole.ASSISTANT,
            content = "",
            isStreaming = true,
        )
        messages.add(userMsg)
        messages.add(aiMsg)
        pendingAttachments.clear()
        inputText = ""
        isStreaming = true

        streamingJob = scope.launch {
            try {
                repository.streamMessage(
                    sessionId = activeConversationId,
                    content = content,
                ).collect { chunk ->
                    // 找到当前流式 AI 消息，追加增量文本
                    val idx = messages.indexOfLast { it.id == aiMsg.id }
                    if (idx >= 0) {
                        val current = messages[idx]
                        messages[idx] = current.copy(content = current.content + chunk)
                    }
                }
            } catch (e: kotlinx.coroutines.CancellationException) {
                // 用户主动取消，正常退出
                Log.d(TAG, "流式聊天被取消: ${e.message}")
            } catch (e: Exception) {
                Log.e(TAG, "流式聊天异常: ${e.message}", e)
                errorMessage = "流式聊天异常: ${e.message}"
            } finally {
                // 标记 AI 消息流式结束
                val idx = messages.indexOfLast { it.id == aiMsg.id }
                if (idx >= 0) {
                    val current = messages[idx]
                    if (current.isStreaming) {
                        messages[idx] = current.copy(isStreaming = false)
                    }
                }
                streamingJob = null
                isStreaming = false
            }
        }
    }

    /**
     * 取消流式：取消协程会触发 SSE 连接关闭，Flow 自然终止
     */
    fun cancelStreaming() {
        streamingJob?.cancel()
        streamingJob = null
        isStreaming = false
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
                isStreaming = isStreaming,
                isUploading = isUploading,
                pendingAttachmentCount = pendingAttachments.size,
                onPickAttachment = { filePicker.launch("*/*") },
                onSend = { sendMessage(inputText.trim()) },
                onCancel = { cancelStreaming() },
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
                    messages.clear()
                },
            )

            // 错误提示
            errorMessage?.let { msg ->
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(MaterialTheme.colorScheme.errorContainer)
                        .padding(12.dp),
                ) {
                    Text(
                        text = msg,
                        color = MaterialTheme.colorScheme.onErrorContainer,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }

            // 消息列表 / 空状态
            if (messages.isEmpty()) {
                EmptyBox(
                    icon = Icons.Outlined.Chat,
                    title = "暂无消息",
                    actionText = "开始新对话",
                    onAction = {
                        sendMessage("你好")
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
 *
 * 布局：附件按钮 + 文本输入框 + 发送/停止按钮
 * - 流式中显示停止按钮（替代发送）
 * - 上传中禁用附件按钮并显示加载指示
 *
 * 2026-07-09 UI 优化：
 * - 输入栏背景使用 surface + 上边框 outlineVariant，视觉分隔更清晰
 * - 发送按钮改用 FilledIconButton + 品牌色背景，替代纯 IconButton
 * - 圆角统一 24dp
 */
@Composable
private fun ChatInputBar(
    text: String,
    onTextChange: (String) -> Unit,
    isStreaming: Boolean,
    isUploading: Boolean,
    pendingAttachmentCount: Int,
    onPickAttachment: () -> Unit,
    onSend: () -> Unit,
    onCancel: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface)
            .padding(horizontal = 12.dp, vertical = 10.dp)
            .imePadding(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        // 附件按钮
        Box {
            IconButton(
                onClick = onPickAttachment,
                enabled = !isUploading && !isStreaming,
            ) {
                Icon(
                    imageVector = Icons.Outlined.AttachFile,
                    contentDescription = "添加附件",
                    tint = if (isUploading || isStreaming) {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    } else {
                        MaterialTheme.colorScheme.primary
                    },
                )
            }
            // 附件计数徽标
            if (pendingAttachmentCount > 0) {
                Box(
                    modifier = Modifier
                        .background(
                            color = MaterialTheme.colorScheme.primary,
                            shape = RoundedCornerShape(8.dp),
                        )
                        .padding(horizontal = 4.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = pendingAttachmentCount.toString(),
                        color = MaterialTheme.colorScheme.onPrimary,
                        style = MaterialTheme.typography.labelSmall,
                    )
                }
            }
        }

        // 上传中加载指示
        if (isUploading) {
            CircularProgressIndicator(
                modifier = Modifier.size(16.dp),
                strokeWidth = 2.dp,
            )
            Spacer(modifier = Modifier.size(4.dp))
        }

        OutlinedTextField(
            value = text,
            onValueChange = onTextChange,
            placeholder = { Text(text = "输入消息…") },
            modifier = Modifier.weight(1f),
            maxLines = 4,
            enabled = !isStreaming,
            shape = RoundedCornerShape(24.dp),
        )

        if (isStreaming) {
            // 停止按钮（保持 IconButton 风格，避免用户误触）
            IconButton(onClick = onCancel) {
                Icon(
                    imageVector = Icons.Outlined.Stop,
                    contentDescription = "停止",
                    tint = MaterialTheme.colorScheme.error,
                )
            }
        } else {
            // 发送按钮：FilledIconButton + 品牌色背景，圆角 16dp
            val sendEnabled = text.isNotBlank() || pendingAttachmentCount > 0
            androidx.compose.material3.FilledIconButton(
                onClick = onSend,
                enabled = sendEnabled,
                shape = RoundedCornerShape(16.dp),
            ) {
                Icon(
                    imageVector = Icons.Outlined.Send,
                    contentDescription = "发送",
                )
            }
        }
    }
}

/**
 * 会话列表（横向滚动）
 *
 * 2026-07-09 UI 优化：
 * - 新建对话按钮用品牌渐变背景 + Add 图标，替代纯 IconButton
 * - 会话卡片圆角 16dp + 选中态加粗
 */
@Composable
private fun ConversationRow(
    conversations: List<Conversation>,
    activeId: String,
    onSelect: (Conversation) -> Unit,
    onNew: () -> Unit,
) {
    LazyRow(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surface),
        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            // 新建对话按钮：品牌渐变背景 + 圆角
            Box(
                modifier = Modifier
                    .background(
                        brush = com.xtys126.open_awa.core.theme.LocalBrandGradient.current,
                        shape = RoundedCornerShape(16.dp),
                    )
                    .clickable { onNew() }
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                contentAlignment = Alignment.Center,
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        imageVector = Icons.Outlined.Add,
                        contentDescription = "新建对话",
                        tint = MaterialTheme.colorScheme.onPrimary,
                        modifier = Modifier.size(18.dp),
                    )
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(
                        text = "新对话",
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.onPrimary,
                        fontWeight = FontWeight.Medium,
                    )
                }
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
                    .clickable { onSelect(conv) }
                    .padding(horizontal = 14.dp, vertical = 8.dp),
            ) {
                Text(
                    text = conv.title,
                    style = MaterialTheme.typography.labelLarge,
                    color = if (isActive) {
                        MaterialTheme.colorScheme.onPrimaryContainer
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    fontWeight = if (isActive) FontWeight.SemiBold else FontWeight.Normal,
                )
            }
        }
    }
}

/**
 * 消息气泡
 *
 * 用户消息右对齐 + 主色调背景，AI 消息左对齐 + surface 背景
 * 流式中的 AI 消息末尾闪烁光标（用 isLoading 圆点替代，避免动画复杂度）
 *
 * 2026-07-09 UI 优化：
 * - 用户消息：品牌色背景 + 右下角小圆角（尾翼效果），其余 16dp
 * - AI 消息：surfaceVariant 背景 + 左下角小圆角（尾翼效果），其余 16dp
 * - 气泡最大宽度 80%，避免长文本占满整行
 * - 流式光标改为品牌色小圆点，更精致
 */
@Composable
private fun MessageBubble(message: UiMessage) {
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
        MaterialTheme.colorScheme.onSurface
    }
    // 尾翼效果：发送方一侧的角落圆角更小
    val bubbleShape = if (isUser) {
        RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp, bottomStart = 16.dp, bottomEnd = 4.dp)
    } else {
        RoundedCornerShape(topStart = 16.dp, topEnd = 16.dp, bottomStart = 4.dp, bottomEnd = 16.dp)
    }

    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = alignment,
    ) {
        // 附件预览（用户消息显示已上传附件的文件名）
        if (message.attachments.isNotEmpty()) {
            Column(
                modifier = Modifier
                    .padding(bottom = 4.dp)
                    .fillMaxWidth(0.8f),
                verticalArrangement = Arrangement.spacedBy(2.dp),
                horizontalAlignment = alignment,
            ) {
                message.attachments.forEach { att ->
                    AttachmentChip(attachment = att)
                }
            }
        }

        Box(
            modifier = Modifier
                .fillMaxWidth(0.8f)
                .background(
                    color = bgColor,
                    shape = bubbleShape,
                )
                .padding(horizontal = 14.dp, vertical = 10.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = if (message.content.isEmpty() && message.isStreaming) {
                        "思考中…"
                    } else {
                        message.content
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = fgColor,
                    modifier = Modifier.weight(1f, fill = false),
                )
                if (message.isStreaming && message.content.isNotEmpty()) {
                    Spacer(modifier = Modifier.size(6.dp))
                    // 流式光标：品牌色小圆点
                    Box(
                        modifier = Modifier
                            .size(8.dp)
                            .background(
                                color = if (isUser) {
                                    MaterialTheme.colorScheme.onPrimary
                                } else {
                                    MaterialTheme.colorScheme.primary
                                },
                                shape = RoundedCornerShape(4.dp),
                            ),
                    )
                }
            }
        }
    }
}

/**
 * 附件缩略行（显示上传后的文件名 + 类型图标）
 */
@Composable
private fun AttachmentChip(attachment: AttachmentResponse) {
    Row(
        modifier = Modifier
            .background(
                color = MaterialTheme.colorScheme.secondaryContainer,
                shape = RoundedCornerShape(8.dp),
            )
            .padding(horizontal = 8.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Icon(
            imageVector = Icons.Outlined.AttachFile,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSecondaryContainer,
            modifier = Modifier.size(12.dp),
        )
        Text(
            text = attachment.originalName,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSecondaryContainer,
        )
    }
}

/**
 * 从 Uri 查询原始文件名
 */
private fun queryFileName(context: Context, uri: Uri): String? {
    return runCatching {
        context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (nameIndex < 0 || !cursor.moveToFirst()) return@use null
            cursor.getString(nameIndex)
        }
    }.getOrNull()
}

/**
 * 从 Uri 读取文件字节
 *
 * @throws java.io.IOException 无法打开输入流时抛出
 */
@Throws(java.io.IOException::class)
private fun readUriBytes(context: Context, uri: Uri): ByteArray {
    return context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
        ?: throw java.io.IOException("无法读取文件: $uri")
}

// 数据类（TODO: 迁移到 data 层 ChatRepository）

private enum class MessageRole { USER, ASSISTANT }

private data class UiMessage(
    val id: String,
    val role: MessageRole,
    val content: String,
    /** 是否处于流式接收中（AI 消息） */
    val isStreaming: Boolean = false,
    /** 用户消息携带的附件列表（已上传） */
    val attachments: List<AttachmentResponse> = emptyList(),
)

private data class Conversation(
    val id: String,
    val title: String,
)
