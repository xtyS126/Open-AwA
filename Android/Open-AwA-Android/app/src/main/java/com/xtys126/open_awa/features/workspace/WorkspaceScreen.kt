package com.xtys126.open_awa.features.workspace

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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.Folder
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
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
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * 工作区页
 *
 * 浏览当前工作区文件：
 * - 顶部路径面包屑
 * - 左侧文件树（缩进展示层级）
 * - 右侧文件内容预览
 *
 * TODO: 接入 WorkspaceRepository 调用后端 /api/workspace/list 与 /api/workspace/read
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun WorkspaceScreen() {
    // 当前路径面包屑
    var currentPath by remember { mutableStateOf(listOf("workspace", "demo-project")) }

    // 当前选中的文件
    var selectedFile by remember { mutableStateOf<FileItem?>(null) }

    // 模拟文件树（包含目录与文件，带缩进层级）
    val fileList = remember {
        listOf(
            FileItem(name = "src", isDirectory = true, depth = 0),
            FileItem(name = "main.py", isDirectory = false, depth = 1, content = "print('hello')\n"),
            FileItem(name = "utils", isDirectory = true, depth = 1),
            FileItem(name = "helpers.py", isDirectory = false, depth = 2, content = "def add(a, b):\n    return a + b\n"),
            FileItem(name = "tests", isDirectory = true, depth = 0),
            FileItem(name = "test_main.py", isDirectory = false, depth = 1, content = "def test_main():\n    pass\n"),
            FileItem(name = "README.md", isDirectory = false, depth = 0, content = "# Demo Project\n"),
            FileItem(name = "pyproject.toml", isDirectory = false, depth = 0, content = "[project]\nname = 'demo'\n"),
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(text = "工作区", style = MaterialTheme.typography.titleMedium) },
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
            // 路径面包屑
            Breadcrumb(path = currentPath)

            // 文件列表
            LazyColumn(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                items(fileList) { file ->
                    FileRow(
                        file = file,
                        isSelected = selectedFile?.name == file.name,
                        onClick = {
                            if (!file.isDirectory) {
                                selectedFile = file
                                // 点击文件时更新面包屑为文件所在目录
                                currentPath = buildList {
                                    add("workspace")
                                    add("demo-project")
                                    if (file.depth > 0) add(file.name)
                                }
                            } else {
                                // TODO: 进入目录，刷新文件列表
                                currentPath = currentPath + file.name
                            }
                        },
                    )
                }
            }

            Spacer(modifier = Modifier.size(0.dp))

            // 文件预览
            FilePreview(file = selectedFile)
        }
    }
}

/**
 * 路径面包屑
 */
@Composable
private fun Breadcrumb(path: List<String>) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        path.forEachIndexed { index, segment ->
            Text(
                text = segment,
                style = MaterialTheme.typography.labelLarge,
                color = if (index == path.lastIndex) {
                    MaterialTheme.colorScheme.onSurface
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
                fontWeight = if (index == path.lastIndex) FontWeight.SemiBold else FontWeight.Normal,
            )
            if (index != path.lastIndex) {
                Icon(
                    imageVector = Icons.Outlined.ChevronRight,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.size(16.dp),
                )
            }
        }
    }
}

/**
 * 文件行
 */
@Composable
private fun FileRow(
    file: FileItem,
    isSelected: Boolean,
    onClick: () -> Unit,
) {
    Card(
        onClick = onClick,
        modifier = Modifier
            .fillMaxWidth()
            .padding(start = (file.depth * 16).dp),
        colors = if (isSelected) {
            CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
        } else {
            CardDefaults.cardColors()
        },
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = if (file.isDirectory) Icons.Outlined.Folder else Icons.Outlined.Description,
                contentDescription = null,
                tint = if (file.isDirectory) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
                modifier = Modifier.size(20.dp),
            )
            Spacer(modifier = Modifier.padding(end = 8.dp))
            Text(
                text = file.name,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

/**
 * 文件内容预览
 */
@Composable
private fun FilePreview(file: FileItem?) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = if (file != null) "预览: ${file.name}" else "预览",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.size(8.dp))
            androidx.compose.foundation.layout.Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState()),
            ) {
                Text(
                    text = file?.content ?: "请选择文件查看内容",
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}

/**
 * 文件数据模型
 */
private data class FileItem(
    val name: String,
    val isDirectory: Boolean,
    val depth: Int,
    val content: String? = null,
)
