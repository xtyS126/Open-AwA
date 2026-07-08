package com.xtys126.open_awa.features.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Brightness6
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Language
import androidx.compose.material.icons.outlined.Logout
import androidx.compose.material.icons.outlined.Mail
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.core.backend.BackendManager
import com.xtys126.open_awa.core.ui.SectionCard

/**
 * 设置页
 *
 * 分组列表（[LazyColumn] + [SectionCard] + [ListItem]）：
 * - 通用：主题切换（亮/暗）、语言（中文/英文）
 * - 后端：服务器后端 URL 配置
 * - 账户：用户名、邮箱、登出
 * - 关于：版本号、开源协议
 *
 * TODO:
 * - 主题切换接入 ThemeStore（DataStore），支持亮/暗/跟随系统三态
 * - 账户信息接入 AuthRepository，登出调用 AuthRepository.logout()
 */
@Composable
fun SettingsScreen() {
    // 通用（TODO: 接入 ThemeStore，当前用本地状态占位）
    var darkTheme by remember { mutableStateOf(false) }
    var languageZh by remember { mutableStateOf(true) }

    // 后端（服务器中心架构：仅配置服务器 URL）
    var remoteUrl by remember { mutableStateOf(BackendManager.getRemoteUrl()) }
    var urlInput by remember { mutableStateOf(remoteUrl) }

    // 账户（TODO: 接入 AuthRepository）
    val username = remember { mutableStateOf("未登录") }
    val email = remember { mutableStateOf("") }

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // 通用分组
        item {
            SectionCard(title = "通用") {
                Column {
                    ListItem(
                        headlineContent = { Text(text = "暗色主题") },
                        supportingContent = { Text(text = "关闭后跟随系统") },
                        leadingContent = {
                            Icon(
                                imageVector = Icons.Outlined.Brightness6,
                                contentDescription = null,
                            )
                        },
                        trailingContent = {
                            Switch(
                                checked = darkTheme,
                                onCheckedChange = {
                                    darkTheme = it
                                    // TODO: 调用 ThemeStore.setDarkTheme(it)
                                },
                            )
                        },
                    )
                    ListItem(
                        headlineContent = { Text(text = "语言") },
                        supportingContent = {
                            Text(text = if (languageZh) "中文" else "English")
                        },
                        leadingContent = {
                            Icon(
                                imageVector = Icons.Outlined.Language,
                                contentDescription = null,
                            )
                        },
                        trailingContent = {
                            Switch(
                                checked = languageZh,
                                onCheckedChange = {
                                    languageZh = it
                                    // TODO: 调用 ThemeStore.setLanguage(if (it) "zh" else "en")
                                },
                            )
                        },
                    )
                }
            }
        }

        // 后端分组
        item {
            SectionCard(title = "后端") {
                Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    ListItem(
                        headlineContent = { Text(text = "服务器后端 URL") },
                        supportingContent = { Text(text = "瘦客户端架构，所有业务由服务器提供") },
                        leadingContent = {
                            Icon(
                                imageVector = Icons.Outlined.Storage,
                                contentDescription = null,
                            )
                        },
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedTextField(
                        value = urlInput,
                        onValueChange = { urlInput = it },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text(text = "https://your-server:8000") },
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Button(
                        onClick = {
                            BackendManager.setRemoteUrl(urlInput)
                            remoteUrl = urlInput
                        },
                    ) {
                        Text(text = "保存")
                    }
                    if (remoteUrl != urlInput) {
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "当前生效：$remoteUrl",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }

        // 账户分组
        item {
            SectionCard(title = "账户") {
                Column {
                    ListItem(
                        headlineContent = { Text(text = "用户名") },
                        supportingContent = { Text(text = username.value) },
                        leadingContent = {
                            Icon(
                                imageVector = Icons.Outlined.Person,
                                contentDescription = null,
                            )
                        },
                    )
                    ListItem(
                        headlineContent = { Text(text = "邮箱") },
                        supportingContent = {
                            Text(text = email.value.ifBlank { "未设置" })
                        },
                        leadingContent = {
                            Icon(
                                imageVector = Icons.Outlined.Mail,
                                contentDescription = null,
                            )
                        },
                    )
                    ListItem(
                        headlineContent = { Text(text = "登出") },
                        leadingContent = {
                            Icon(
                                imageVector = Icons.Outlined.Logout,
                                contentDescription = null,
                            )
                        },
                    )
                }
            }
        }

        // 关于分组
        item {
            SectionCard(title = "关于") {
                Column {
                    ListItem(
                        headlineContent = { Text(text = "版本号") },
                        supportingContent = { Text(text = "1.0.0") },
                        leadingContent = {
                            Icon(
                                imageVector = Icons.Outlined.Info,
                                contentDescription = null,
                            )
                        },
                    )
                    ListItem(
                        headlineContent = { Text(text = "开源协议") },
                        supportingContent = { Text(text = "MIT License") },
                    )
                }
            }
        }
    }
}
