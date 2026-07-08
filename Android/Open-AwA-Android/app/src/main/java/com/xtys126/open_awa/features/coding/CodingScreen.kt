package com.xtys126.open_awa.features.coding

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp

/**
 * 编码页
 *
 * 提供轻量代码执行环境：
 * - 顶部语言选择（Python / JavaScript / Shell）
 * - 中部代码编辑器（等宽字体）
 * - 底部运行输出区
 *
 * TODO: 接入 CodeExecutionRepository 调用后端 /api/code/run 接口
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CodingScreen() {
    // 支持的语言列表
    val languages = remember { listOf("Python", "JavaScript", "Shell") }

    // 当前选中语言
    var selectedLanguage by remember { mutableStateOf("Python") }

    // 代码内容
    var code by remember { mutableStateOf("") }

    // 运行输出
    var output by remember { mutableStateOf("") }

    // 运行中状态
    var isRunning by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = "编码", style = MaterialTheme.typography.titleMedium) },
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // 语言选择 Chip 行
            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                languages.forEach { lang ->
                    FilterChip(
                        selected = selectedLanguage == lang,
                        onClick = { selectedLanguage = lang },
                        label = { Text(text = lang) },
                    )
                }
            }

            // 代码编辑器
            Text(
                text = "代码",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedTextField(
                value = code,
                onValueChange = { code = it },
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
                placeholder = {
                    Text(
                        text = "在此输入代码...",
                        fontFamily = FontFamily.Monospace,
                    )
                },
                textStyle = MaterialTheme.typography.bodyMedium.copy(
                    fontFamily = FontFamily.Monospace,
                ),
                maxLines = Int.MAX_VALUE,
            )

            // 运行按钮
            Button(
                onClick = {
                    // TODO: 调用 Repository 提交代码执行
                    if (code.isBlank()) {
                        output = "[提示] 代码不能为空"
                        return@Button
                    }
                    isRunning = true
                    // 模拟执行：实际应调用后端
                    output = buildString {
                        appendLine("[运行] $selectedLanguage 代码开始执行")
                        appendLine(">>> ${code.lineSequence().firstOrNull() ?: ""}")
                        appendLine("[完成] 执行耗时 0.12s")
                    }
                    isRunning = false
                },
                enabled = !isRunning,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(
                    imageVector = Icons.Outlined.PlayArrow,
                    contentDescription = null,
                )
                Spacer(modifier = Modifier.padding(start = 4.dp))
                Text(text = if (isRunning) "运行中" else "运行")
            }

            HorizontalDivider()

            // 输出区
            Text(
                text = "输出",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
                    .verticalScroll(rememberScrollState()),
            ) {
                Text(
                    text = output.ifBlank { "等待运行..." },
                    style = MaterialTheme.typography.bodyMedium,
                    fontFamily = FontFamily.Monospace,
                    color = if (output.isBlank()) {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    } else {
                        MaterialTheme.colorScheme.onSurface
                    },
                )
            }
        }
    }
}
