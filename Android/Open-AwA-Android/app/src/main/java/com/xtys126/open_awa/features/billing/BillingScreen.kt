package com.xtys126.open_awa.features.billing

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AccountBalanceWallet
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.xtys126.open_awa.core.ui.SectionHeader

/**
 * 计费页
 *
 * 展示账户余额、消费记录、套餐对比
 * 当前数据为 remember { mutableStateOf } 模拟，待 Repository 接入后替换
 */
@Composable
fun BillingScreen() {
    // TODO: 接入 BillingRepository 加载真实余额与消费记录
    val balance by remember { mutableStateOf("¥ 128.50") }
    var records by remember { mutableStateOf(sampleRecords()) }
    val plans = remember { samplePlans() }

    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { BalanceCard(balance) }
        item { SectionHeader("消费记录") }
        items(records) { record ->
            RecordCard(record)
        }
        item { SectionHeader("套餐对比") }
        item { PlansRow(plans) }
        item { Spacer(modifier = Modifier.height(16.dp)) }
    }
}

/**
 * 余额卡片
 *
 * 大字号显示余额，附充值按钮
 */
@Composable
private fun BalanceCard(balance: String) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer,
            contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
        ),
    ) {
        Column(modifier = Modifier.padding(20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = Icons.Outlined.AccountBalanceWallet,
                    contentDescription = null,
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "当前余额",
                    style = MaterialTheme.typography.labelLarge,
                )
            }
            Spacer(modifier = Modifier.height(12.dp))
            Text(
                text = balance,
                style = MaterialTheme.typography.displayMedium,
                fontWeight = FontWeight.Bold,
            )
            Spacer(modifier = Modifier.height(16.dp))
            Button(onClick = { /* TODO: 跳转充值页 */ }) {
                Icon(
                    imageVector = Icons.Outlined.Add,
                    contentDescription = null,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text("充值")
            }
        }
    }
}

/**
 * 消费记录卡片
 */
@Composable
private fun RecordCard(record: BillingRecord) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = record.model,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Medium,
                )
                Text(
                    text = record.date,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Text(
                text = record.amount,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}

/**
 * 套餐对比行（3 列等宽）
 */
@Composable
private fun PlansRow(plans: List<Plan>) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        plans.forEach { plan ->
            PlanCard(plan, Modifier.weight(1f))
        }
    }
}

@Composable
private fun PlanCard(plan: Plan, modifier: Modifier = Modifier) {
    Card(modifier = modifier) {
        Column(
            modifier = Modifier.padding(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = plan.name,
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = plan.price,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.primary,
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = plan.feature,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

/**
 * 计费记录数据模型
 */
private data class BillingRecord(
    val date: String,
    val model: String,
    val amount: String,
)

/**
 * 套餐数据模型
 */
private data class Plan(
    val name: String,
    val price: String,
    val feature: String,
)

private fun sampleRecords(): List<BillingRecord> = listOf(
    BillingRecord("2026-07-09 14:32", "GPT-4", "- ¥0.45"),
    BillingRecord("2026-07-09 11:08", "Claude 3.5", "- ¥0.32"),
    BillingRecord("2026-07-08 20:15", "GPT-4", "- ¥0.18"),
    BillingRecord("2026-07-08 16:50", "Gemini Pro", "- ¥0.12"),
    BillingRecord("2026-07-08 09:22", "Claude 3.5", "- ¥0.28"),
)

private fun samplePlans(): List<Plan> = listOf(
    Plan("入门", "¥0", "5 条/天"),
    Plan("标准", "¥29", "100 条/天"),
    Plan("专业", "¥99", "无限调用"),
)
