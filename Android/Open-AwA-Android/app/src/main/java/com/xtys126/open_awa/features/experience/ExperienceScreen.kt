package com.xtys126.open_awa.features.experience

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.Star
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material.icons.outlined.Warning
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.core.ui.FilterChipRow

/**
 * 经验页
 *
 * 顶部筛选 Chip + 2 列经验卡片网格
 * 当前数据为 remember { mutableStateOf } 模拟，待 Repository 接入后替换
 */
@Composable
fun ExperienceScreen() {
    var selectedFilter by remember { mutableStateOf(0) }
    // TODO: 接入 ExperienceRepository 加载经验列表
    val experiences by remember { mutableStateOf(sampleExperiences()) }
    val filters = remember { listOf("全部", "技能", "陷阱", "优化") }

    val filtered = remember(experiences, selectedFilter) {
        if (selectedFilter == 0) {
            experiences
        } else {
            experiences.filter { it.category.label == filters[selectedFilter] }
        }
    }

    Column(modifier = Modifier.fillMaxSize()) {
        FilterChipRow(
            options = filters,
            selected = selectedFilter,
            onSelect = { selectedFilter = it },
        )
        LazyVerticalGrid(
            columns = GridCells.Fixed(2),
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(16.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            items(filtered) { experience ->
                ExperienceCard(experience)
            }
        }
    }
}

/**
 * 经验卡片
 */
@Composable
private fun ExperienceCard(experience: Experience) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = experience.category.icon,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = experience.category.label,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = experience.title,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "来源：${experience.source}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = Icons.Outlined.Star,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.tertiary,
                    modifier = Modifier.size(16.dp),
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text(
                    text = experience.rating.toString(),
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.Medium,
                    color = MaterialTheme.colorScheme.tertiary,
                )
            }
        }
    }
}

/**
 * 经验类别枚举
 *
 * 与筛选 Chip 一一对应：技能 / 陷阱 / 优化
 */
private enum class ExperienceCategory(val label: String, val icon: ImageVector) {
    SKILL("技能", Icons.Outlined.Bolt),
    PITFALL("陷阱", Icons.Outlined.Warning),
    OPTIMIZATION("优化", Icons.Outlined.Tune),
}

/**
 * 经验数据模型
 */
private data class Experience(
    val title: String,
    val source: String,
    val rating: Int,
    val category: ExperienceCategory,
)

private fun sampleExperiences(): List<Experience> = listOf(
    Experience("SSE 流式断线重连", "Claude", 5, ExperienceCategory.PITFALL),
    Experience("React useMemo 优化列表", "GPT-4", 4, ExperienceCategory.OPTIMIZATION),
    Experience("SQL 注入防护方案", "Gemini", 5, ExperienceCategory.SKILL),
    Experience("异步任务超时处理", "Claude", 4, ExperienceCategory.SKILL),
    Experience("暗色主题适配陷阱", "GPT-4", 3, ExperienceCategory.PITFALL),
    Experience("Compose 性能优化", "Claude", 5, ExperienceCategory.OPTIMIZATION),
)
