package com.xtys126.open_awa.features.settings

import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Brightness6
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Language
import androidx.compose.material.icons.outlined.Logout
import androidx.compose.material.icons.outlined.Mail
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.QrCodeScanner
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.core.backend.BackendManager
import com.xtys126.open_awa.core.backend.QrScanResult
import com.xtys126.open_awa.core.backend.rememberQrScannerLauncher
import com.xtys126.open_awa.core.theme.LocalBrandGradient
import com.xtys126.open_awa.core.ui.SectionCard

/**
 * 设置页
 *
 * 分组列表（[LazyColumn] + [SectionCard] + [ListItem]）：
 * - 顶部品牌头部卡片（Logo + 应用名 + 版本）
 * - 通用：主题切换（亮/暗）、语言（中文/英文）
 * - 后端：扫码链接后端 + 服务器后端 URL 配置
 * - 账户：用户名、邮箱、登出
 * - 关于：版本号、开源协议
 *
 * 2026-07-09 UI 优化：
 * - 顶部增加品牌头部卡片（渐变 Logo + 应用名 + tagline + 版本）
 * - 各分组 leadingContent 图标用品牌色 tint
 * - 扫码按钮用品牌渐变背景，更醒目
 * - 登出按钮改为 error 色 OutlinedButton
 *
 * 扫码功能：
 * - 顶部"扫码链接后端"按钮调用 [rememberQrScannerLauncher]
 * - 扫码成功后自动填充 URL 输入框并保存到 [BackendManager]
 * - 扫码失败显示错误提示（如 URL 不合法、权限被拒绝等）
 *
 * TODO:
 * - 主题切换接入 ThemeStore（DataStore），支持亮/暗/跟随系统三态
 * - 账户信息接入 AuthRepository，登出调用 AuthRepository.logout()
 */
@Composable
fun SettingsScreen() {
    val context = LocalContext.current

    // 通用（TODO: 接入 ThemeStore，当前用本地状态占位）
    var darkTheme by remember { mutableStateOf(false) }
    var languageZh by remember { mutableStateOf(true) }

    // 后端（服务器中心架构：仅配置服务器 URL）
    var remoteUrl by remember { mutableStateOf(BackendManager.getRemoteUrl()) }
    var urlInput by remember { mutableStateOf(remoteUrl) }

    // 账户（TODO: 接入 AuthRepository）
    val username = remember { mutableStateOf("未登录") }
    val email = remember { mutableStateOf("") }

    // 扫码启动器：扫到合法 URL 后自动写入 BackendManager
    val launchScan = rememberQrScannerLauncher { result: QrScanResult ->
        if (result.success) {
            // 扫码成功：URL 已由 launcher 写入 BackendManager，同步刷新本地状态
            result.url?.let { scannedUrl ->
                urlInput = scannedUrl
                remoteUrl = scannedUrl
            }
            Toast.makeText(context, "后端地址已更新", Toast.LENGTH_SHORT).show()
        } else {
            // 扫码失败：显示错误原因（取消扫码 / URL 不合法 / 权限被拒绝）
            Toast.makeText(
                context,
                result.errorMessage ?: "扫码失败",
                Toast.LENGTH_LONG,
            ).show()
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // 顶部品牌头部卡片
        item { BrandHeaderCard() }

        // 通用分组
        item {
            SectionCard(title = "通用") {
                Column {
                    ListItem(
                        headlineContent = { Text(text = "暗色主题") },
                        supportingContent = { Text(text = "关闭后跟随系统") },
                        leadingContent = {
                            BrandIcon(imageVector = Icons.Outlined.Brightness6)
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
                            BrandIcon(imageVector = Icons.Outlined.Language)
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
                    // 扫码链接后端按钮：品牌渐变背景
                    Button(
                        onClick = { launchScan() },
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = MaterialTheme.colorScheme.primary,
                        ),
                    ) {
                        Icon(
                            imageVector = Icons.Outlined.QrCodeScanner,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.onPrimary,
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "扫码链接后端",
                            color = MaterialTheme.colorScheme.onPrimary,
                        )
                    }
                    Spacer(modifier = Modifier.height(12.dp))
                    ListItem(
                        headlineContent = { Text(text = "服务器后端 URL") },
                        supportingContent = { Text(text = "瘦客户端架构，所有业务由服务器提供") },
                        leadingContent = {
                            BrandIcon(imageVector = Icons.Outlined.Storage)
                        },
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedTextField(
                        value = urlInput,
                        onValueChange = { urlInput = it },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        label = { Text(text = "https://your-server:8000") },
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    Row(modifier = Modifier.fillMaxWidth()) {
                        Button(
                            onClick = {
                                BackendManager.setRemoteUrl(urlInput)
                                remoteUrl = urlInput
                                Toast.makeText(context, "已保存", Toast.LENGTH_SHORT).show()
                            },
                            shape = RoundedCornerShape(12.dp),
                        ) {
                            Text(text = "保存")
                        }
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
                            BrandIcon(imageVector = Icons.Outlined.Person)
                        },
                    )
                    ListItem(
                        headlineContent = { Text(text = "邮箱") },
                        supportingContent = {
                            Text(text = email.value.ifBlank { "未设置" })
                        },
                        leadingContent = {
                            BrandIcon(imageVector = Icons.Outlined.Mail)
                        },
                    )
                    // 登出按钮：error 色 OutlinedButton，更明显
                    Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                        OutlinedButton(
                            onClick = {
                                // TODO: 调用 AuthRepository.logout()
                                Toast.makeText(context, "已登出", Toast.LENGTH_SHORT).show()
                            },
                            modifier = Modifier.fillMaxWidth(),
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.outlinedButtonColors(
                                contentColor = MaterialTheme.colorScheme.error,
                            ),
                        ) {
                            Icon(
                                imageVector = Icons.Outlined.Logout,
                                contentDescription = null,
                                tint = MaterialTheme.colorScheme.error,
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Text(
                                text = "登出",
                                color = MaterialTheme.colorScheme.error,
                            )
                        }
                    }
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
                            BrandIcon(imageVector = Icons.Outlined.Info)
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

/**
 * 品牌头部卡片
 *
 * 2026-07-09 新增：设置页顶部品牌展示区
 * - 大号 Logo（品牌渐变圆角方块）
 * - 应用名（titleLarge + SemiBold）
 * - tagline（labelMedium + onSurfaceVariant）
 * - 版本号（labelSmall）
 */
@Composable
private fun BrandHeaderCard() {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface,
        ),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            // Logo：品牌渐变圆角方块
            Box(
                modifier = Modifier
                    .size(64.dp)
                    .clip(RoundedCornerShape(16.dp))
                    .background(LocalBrandGradient.current),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = "A",
                    color = MaterialTheme.colorScheme.onPrimary,
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.Bold,
                )
            }
            Spacer(modifier = Modifier.height(12.dp))
            Text(
                text = "Open-AwA",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(modifier = Modifier.height(2.dp))
            Text(
                text = "AI Agent 实验性平台",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.height(6.dp))
            Text(
                text = "v1.0.0",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * 品牌色图标
 *
 * 用于 ListItem 的 leadingContent，统一品牌色 tint
 *
 * @param imageVector 图标向量
 */
@Composable
private fun BrandIcon(imageVector: androidx.compose.ui.graphics.vector.ImageVector) {
    Box(
        modifier = Modifier
            .size(36.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(MaterialTheme.colorScheme.primaryContainer),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = imageVector,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onPrimaryContainer,
            modifier = Modifier.size(20.dp),
        )
    }
}
