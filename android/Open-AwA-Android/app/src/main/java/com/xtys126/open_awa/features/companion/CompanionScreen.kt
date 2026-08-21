package com.xtys126.open_awa.features.companion

import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Bedtime
import androidx.compose.material.icons.outlined.Favorite
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.Timeline
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.core.ui.ErrorBox
import com.xtys126.open_awa.core.ui.LoadingBox
import com.xtys126.open_awa.core.ui.SectionCard
import com.xtys126.open_awa.core.ui.StatCard
import com.xtys126.open_awa.data.CompanionBeliefNode
import com.xtys126.open_awa.data.CompanionRepository
import com.xtys126.open_awa.data.CompanionStateResponse
import kotlinx.coroutines.launch

/**
 * 陪伴心智页
 *
 * 对接后端陪伴系统（/api/companion，commit 199ea5be 引入），
 * 展示陪伴者的心智演化状态并提供睡眠整合操作：
 *
 * 1. 顶部统计卡：羁绊等级 / 心智轮次 / 累计对话
 * 2. 情绪状态卡：主/副情绪 + 强度进度条 + 效价说明（OCC 评估模型）
 * 3. 信念网络卡：五个心理维度（人际信赖/自我价值/责任优先/脆弱防御/对你的好感）
 *    的当前值、应变（可恢复压力）与负荷（不可逆损伤）进度条
 * 4. 引导文本卡：后端渲染的当前情绪与理性/情感双通道占比
 * 5. 涌现弧线卡：观察者检测到的信念演化轨迹
 * 6. 睡眠整合按钮：POST /api/companion/sleep，触发应变恢复、
 *    情绪衰减、记忆整合、人格存档与观察者分析
 *
 * 数据在进入页面时加载，睡眠整合成功后自动刷新状态。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CompanionScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val repository = remember { CompanionRepository() }

    // 心智状态与加载/错误状态
    var state by remember { mutableStateOf<CompanionStateResponse?>(null) }
    var isLoading by remember { mutableStateOf(true) }
    var errorMessage by remember { mutableStateOf<String?>(null) }

    // 睡眠整合进行中标记
    var isSleeping by remember { mutableStateOf(false) }

    /** 拉取心智状态 */
    fun refresh() {
        scope.launch {
            isLoading = true
            errorMessage = null
            runCatching { repository.getState() }
                .onSuccess { result ->
                    state = result
                    isLoading = false
                }
                .onFailure { e ->
                    errorMessage = e.message ?: "拉取心智状态失败"
                    isLoading = false
                }
        }
    }

    // 进入页面时拉取心智状态
    LaunchedEffect(Unit) { refresh() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = "陪伴心智",
                        style = MaterialTheme.typography.titleMedium,
                    )
                },
            )
        },
    ) { innerPadding ->
        when {
            isLoading -> LoadingBox(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding),
            )

            errorMessage != null -> ErrorBox(
                message = errorMessage ?: "",
                onRetry = { refresh() },
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding),
            )

            state != null -> CompanionContent(
                state = state!!,
                isSleeping = isSleeping,
                onSleep = {
                    scope.launch {
                        isSleeping = true
                        runCatching { repository.triggerSleep() }
                            .onSuccess {
                                Toast.makeText(context, "睡眠整合完成", Toast.LENGTH_SHORT).show()
                                // 整合完成后重新拉取最新心智状态
                                runCatching { repository.getState() }
                                    .onSuccess { result -> state = result }
                                isSleeping = false
                            }
                            .onFailure { e ->
                                Toast.makeText(
                                    context,
                                    "睡眠整合失败: ${e.message}",
                                    Toast.LENGTH_SHORT,
                                ).show()
                                isSleeping = false
                            }
                    }
                },
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding),
            )
        }
    }
}

/**
 * 陪伴心智内容区
 *
 * @param state 心智状态响应
 * @param isSleeping 睡眠整合进行中标记
 * @param onSleep 睡眠整合回调
 * @param modifier 修饰符
 */
@Composable
private fun CompanionContent(
    state: CompanionStateResponse,
    isSleeping: Boolean,
    onSleep: () -> Unit,
    modifier: Modifier = Modifier,
) {
    LazyColumn(
        modifier = modifier.padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // 顶部统计卡：羁绊等级 / 心智轮次 / 累计对话
        item {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 8.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                StatCard(
                    title = "羁绊等级",
                    value = "Lv.${state.bondLevel}",
                    icon = Icons.Outlined.Favorite,
                    modifier = Modifier.weight(1f),
                )
                StatCard(
                    title = "心智轮次",
                    value = state.turn.toString(),
                    icon = Icons.Outlined.Timeline,
                    modifier = Modifier.weight(1f),
                )
                StatCard(
                    title = "累计对话",
                    value = state.totalConversations.toString(),
                    icon = Icons.Outlined.ChatBubbleOutline,
                    modifier = Modifier.weight(1f),
                )
            }
        }

        // 情绪状态卡
        item {
            SectionCard(title = "情绪状态") {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = CompanionRepository.emotionLabel(state.emotion.primary),
                        style = MaterialTheme.typography.headlineSmall,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    if (state.emotion.secondary != state.emotion.primary &&
                        state.emotion.secondary != "neutral"
                    ) {
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "/ ${CompanionRepository.emotionLabel(state.emotion.secondary)}",
                            style = MaterialTheme.typography.titleMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(modifier = Modifier.weight(1f))
                    if (state.emotion.ambivalence) {
                        Text(
                            text = "情绪矛盾",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.tertiary,
                        )
                    }
                }
                Spacer(modifier = Modifier.height(12.dp))
                MetricBar(
                    label = "强度",
                    value = state.emotion.intensity,
                )
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "效价 ${formatSigned(state.emotion.valence)}（正值积极，负值消极）",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        // 引导文本卡
        if (state.guidance.isNotBlank()) {
            item {
                SectionCard(title = "当前引导") {
                    Text(
                        text = state.guidance,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }

        // 信念网络卡
        if (state.beliefs.isNotEmpty()) {
            item {
                SectionCard(title = "信念网络") {
                    Text(
                        text = "心理维度随对话确定性演化：应变是可恢复的压力，负荷是不可逆的损伤",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(modifier = Modifier.height(12.dp))
                    state.beliefs.forEach { (key, node) ->
                        BeliefItem(name = CompanionRepository.beliefLabel(key), node = node)
                        Spacer(modifier = Modifier.height(12.dp))
                    }
                }
            }
        }

        // 涌现弧线卡
        if (state.arcs.isNotEmpty()) {
            item {
                SectionCard(title = "涌现弧线") {
                    state.arcs.forEach { arc ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 4.dp),
                        ) {
                            Text(
                                text = CompanionRepository.beliefLabel(arc.belief),
                                style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.Medium,
                            )
                            Spacer(modifier = Modifier.width(12.dp))
                            Text(
                                text = arc.arc,
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
            }
        }

        // 相识时间线
        if (state.firstMetAt != null) {
            item {
                SectionCard(title = "时间线") {
                    TimelineRow(label = "初次相识", value = state.firstMetAt ?: "")
                    if (state.lastInteractionAt != null) {
                        TimelineRow(label = "最近互动", value = state.lastInteractionAt ?: "")
                    }
                }
            }
        }

        // 睡眠整合操作卡
        item {
            Card(
                modifier = Modifier.fillMaxWidth(),
                elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
                shape = RoundedCornerShape(16.dp),
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = Icons.Outlined.Bedtime,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                        )
                        Spacer(modifier = Modifier.width(12.dp))
                        Column(modifier = Modifier.weight(1f)) {
                            Text(
                                text = "睡眠整合",
                                style = MaterialTheme.typography.titleSmall,
                                fontWeight = FontWeight.SemiBold,
                            )
                            Text(
                                text = "应变恢复、情绪衰减、记忆整合与人格存档",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                        if (isSleeping) {
                            CircularProgressIndicator(
                                modifier = Modifier.width(24.dp).height(24.dp),
                                strokeWidth = 2.dp,
                            )
                        } else {
                            Button(onClick = onSleep) {
                                Icon(
                                    imageVector = Icons.Outlined.AutoAwesome,
                                    contentDescription = null,
                                    modifier = Modifier.width(18.dp).height(18.dp),
                                )
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("整合")
                            }
                        }
                    }
                }
            }
        }

        // 底部留白
        item { Spacer(modifier = Modifier.height(16.dp)) }
    }
}

/**
 * 信念维度条目
 *
 * 展示单个心理维度的当前值、应变与负荷三条进度条。
 *
 * @param name 维度中文显示名
 * @param node 信念维度状态
 */
@Composable
private fun BeliefItem(name: String, node: CompanionBeliefNode) {
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = name,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Medium,
            )
            Spacer(modifier = Modifier.weight(1f))
            Text(
                text = "值 ${"%.2f".format(node.value)}",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        Spacer(modifier = Modifier.height(6.dp))
        MetricBar(label = "当前值", value = node.value, color = MaterialTheme.colorScheme.primary)
        Spacer(modifier = Modifier.height(4.dp))
        MetricBar(label = "应变", value = node.strain, color = MaterialTheme.colorScheme.tertiary)
        Spacer(modifier = Modifier.height(4.dp))
        MetricBar(label = "负荷", value = node.load, color = MaterialTheme.colorScheme.error)
    }
}

/**
 * 度量进度条
 *
 * @param label 度量名称
 * @param value 数值（自动钳制到 [0, 1]）
 * @param color 进度条颜色（默认主色）
 */
@Composable
private fun MetricBar(
    label: String,
    value: Float,
    color: androidx.compose.ui.graphics.Color = MaterialTheme.colorScheme.primary,
) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(40.dp),
        )
        LinearProgressIndicator(
            progress = { value.coerceIn(0f, 1f) },
            color = color,
            modifier = Modifier
                .weight(1f)
                .height(6.dp),
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(
            text = "%.2f".format(value),
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.width(32.dp),
        )
    }
}

/**
 * 时间线行
 *
 * @param label 标签（初次相识/最近互动）
 * @param value ISO 时间字符串
 */
@Composable
private fun TimelineRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(modifier = Modifier.weight(1f))
        Text(
            text = formatIsoTime(value),
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

/**
 * 格式化带符号的数值（效价展示用）
 *
 * @param value 数值
 * @return 形如 +0.35 / -0.20 / 0.00 的字符串
 */
private fun formatSigned(value: Float): String =
    if (value >= 0) "+%.2f".format(value) else "%.2f".format(value)

/**
 * 格式化 ISO 时间字符串为可读形式
 *
 * @param iso ISO 8601 字符串（如 2026-08-19T10:30:00.123456+00:00）
 * @return 截取到分钟的本地可读形式（如 2026-08-19 10:30），解析失败原样返回
 */
private fun formatIsoTime(iso: String): String {
    // 截取日期与时间到分钟（去掉秒与毫秒及时区后缀）
    val datePart = iso.take(10)
    val timePart = iso.drop(11).take(5)
    return if (timePart.length == 5) "$datePart $timePart" else iso
}
