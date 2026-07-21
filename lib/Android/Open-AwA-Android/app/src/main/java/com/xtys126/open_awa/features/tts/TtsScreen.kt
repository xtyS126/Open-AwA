package com.xtys126.open_awa.features.tts

import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * TTS 语音合成页
 *
 * 文本转语音工具：
 * - 文本输入框
 * - 模型选择 Chip
 * - 语速 / 音调滑块
 * - 播放按钮
 * - 历史记录列表
 *
 * TODO: 接入 TtsRepository 调用后端 /api/tts/synthesize
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TtsScreen() {
    // 文本输入
    var inputText by remember { mutableStateOf("") }

    // 可选模型
    val models = remember { listOf("标准", "情感", "克隆") }
    var selectedModel by remember { mutableStateOf("标准") }

    // 语速（0.5x - 2.0x）
    var speed by remember { mutableFloatStateOf(1.0f) }

    // 音调（0.5 - 2.0）
    var pitch by remember { mutableFloatStateOf(1.0f) }

    // 历史记录
    var history by remember {
        mutableStateOf(
            listOf(
                TtsHistoryItem(id = "1", text = "欢迎使用 Open-AwA TTS 服务。", model = "标准", duration = "3.2s"),
                TtsHistoryItem(id = "2", text = "今日天气晴朗，适合户外活动。", model = "情感", duration = "4.5s"),
            ),
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = "TTS 语音合成", style = MaterialTheme.typography.titleMedium) },
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // 文本输入
            Text(
                text = "合成文本",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedTextField(
                value = inputText,
                onValueChange = { inputText = it },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(120.dp),
                placeholder = { Text(text = "请输入要合成的文本...") },
                maxLines = 5,
            )

            // 模型选择
            Text(
                text = "模型",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                models.forEach { model ->
                    AssistChip(
                        onClick = { selectedModel = model },
                        label = { Text(text = model) },
                        enabled = true,
                    )
                }
            }

            // 语速滑块
            Text(
                text = "语速: ${"%.1f".format(speed)}x",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Slider(
                value = speed,
                onValueChange = { speed = it },
                valueRange = 0.5f..2.0f,
                steps = 14,
            )

            // 音调滑块
            Text(
                text = "音调: ${"%.1f".format(pitch)}",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Slider(
                value = pitch,
                onValueChange = { pitch = it },
                valueRange = 0.5f..2.0f,
                steps = 14,
            )

            // 播放按钮
            Button(
                onClick = {
                    // TODO: 调用 TtsRepository.synthesize 提交合成
                    if (inputText.isBlank()) return@Button
                    val newItem = TtsHistoryItem(
                        id = (history.size + 1).toString(),
                        text = inputText,
                        model = selectedModel,
                        duration = "${"%.1f".format(inputText.length / 5.0)}s",
                    )
                    history = listOf(newItem) + history
                    inputText = ""
                },
                modifier = Modifier.fillMaxWidth(),
                enabled = inputText.isNotBlank(),
            ) {
                Icon(imageVector = Icons.Outlined.PlayArrow, contentDescription = null)
                Spacer(modifier = Modifier.padding(start = 4.dp))
                Text(text = "合成并播放")
            }

            HorizontalDivider()

            // 历史记录
            Text(
                text = "历史记录",
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(240.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(history, key = { it.id }) { item ->
                    TtsHistoryCard(item = item)
                }
            }
            Spacer(modifier = Modifier.size(0.dp))
        }
    }
}

/**
 * TTS 历史记录卡片
 */
@Composable
private fun TtsHistoryCard(item: TtsHistoryItem) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(modifier = Modifier.padding(12.dp)) {
            Text(
                text = item.text,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 2,
            )
            Spacer(modifier = Modifier.size(4.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = "模型: ${item.model}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = item.duration,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/**
 * TTS 历史记录数据模型
 */
private data class TtsHistoryItem(
    val id: String,
    val text: String,
    val model: String,
    val duration: String,
)
