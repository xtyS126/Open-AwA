package com.xtys126.open_awa.features.skills

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/**
 * 技能页
 *
 * 两个 Tab：已安装 / 市场
 * 已安装 Tab 展示技能卡片与启用/禁用 Switch
 * 市场 Tab 展示技能卡片与安装按钮
 * 当前数据为 remember { mutableStateOf } 模拟，待 Repository 接入后替换
 */
@Composable
fun SkillsScreen() {
    var selectedTab by remember { mutableStateOf(0) }
    // TODO: 接入 SkillsRepository 加载已安装技能与市场列表
    var installedSkills by remember { mutableStateOf(sampleInstalledSkills()) }
    val marketSkills by remember { mutableStateOf(sampleMarketSkills()) }

    Column(modifier = Modifier.fillMaxSize()) {
        TabRow(selectedTabIndex = selectedTab) {
            Tab(
                selected = selectedTab == 0,
                onClick = { selectedTab = 0 },
                text = { Text("已安装") },
            )
            Tab(
                selected = selectedTab == 1,
                onClick = { selectedTab = 1 },
                text = { Text("市场") },
            )
        }
        when (selectedTab) {
            0 -> InstalledSkillsList(
                skills = installedSkills,
                onToggle = { skill ->
                    // TODO: 调用 SkillsRepository.toggleSkill(skill.id, enabled)
                    installedSkills = installedSkills.map {
                        if (it.id == skill.id) it.copy(enabled = !it.enabled) else it
                    }
                },
            )
            1 -> MarketSkillsList(marketSkills)
        }
    }
}

@Composable
private fun InstalledSkillsList(
    skills: List<Skill>,
    onToggle: (Skill) -> Unit,
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        items(skills) { skill ->
            InstalledSkillCard(skill, onToggle)
        }
    }
}

@Composable
private fun MarketSkillsList(skills: List<Skill>) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        items(skills) { skill ->
            MarketSkillCard(skill)
        }
    }
}

/**
 * 已安装技能卡片（含启用/禁用 Switch）
 */
@Composable
private fun InstalledSkillCard(skill: Skill, onToggle: (Skill) -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Outlined.Bolt,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = skill.name,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Medium,
                )
                Text(
                    text = skill.description,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Switch(
                checked = skill.enabled,
                onCheckedChange = { onToggle(skill) },
            )
        }
    }
}

/**
 * 市场技能卡片（含安装按钮）
 */
@Composable
private fun MarketSkillCard(skill: Skill) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Outlined.Bolt,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
            )
            Spacer(modifier = Modifier.width(12.dp))
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = skill.name,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Medium,
                )
                Text(
                    text = skill.description,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Button(onClick = { /* TODO: 调用 SkillsRepository.installSkill(skill.id) */ }) {
                Icon(
                    imageVector = Icons.Outlined.Download,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text("安装")
            }
        }
    }
}

/**
 * 技能数据模型
 */
private data class Skill(
    val id: String,
    val name: String,
    val description: String,
    val enabled: Boolean = false,
)

private fun sampleInstalledSkills(): List<Skill> = listOf(
    Skill("1", "网络搜索", "实时检索互联网信息", enabled = true),
    Skill("2", "代码执行", "在沙箱中运行 Python 代码", enabled = true),
    Skill("3", "文件读取", "读取本地文件内容", enabled = false),
    Skill("4", "图像识别", "识别图像中的物体与文字", enabled = true),
)

private fun sampleMarketSkills(): List<Skill> = listOf(
    Skill("101", "数据库查询", "自然语言转 SQL 查询"),
    Skill("102", "邮件发送", "通过 SMTP 发送邮件"),
    Skill("103", "PDF 解析", "提取 PDF 文本与表格"),
    Skill("104", "翻译", "多语言互译"),
)
