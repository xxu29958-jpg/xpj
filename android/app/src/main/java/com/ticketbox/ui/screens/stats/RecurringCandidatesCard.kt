package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals

@Composable
internal fun RecurringCandidatesCard(candidates: List<RecurringCandidate>) {
    if (candidates.isEmpty()) return
    val currencyDisplay = LocalCurrencyDisplay.current
    val visuals = LocalThemeVisuals.current
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "固定支出候选（未确认）",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = "${candidates.size} 项",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
            Text(
                text = "根据最近账单识别，仅供参考，不会自动入账；确认后才进入正式固定支出。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            candidates.take(5).forEachIndexed { index, candidate ->
                if (index > 0) {
                    HorizontalDivider(color = visuals.chipUnselected.copy(alpha = 0.72f))
                }
                RecurringCandidateRow(candidate, currencyDisplay)
            }
        }
    }
}

@Composable
internal fun RecurringItemsSummaryCard(items: List<RecurringItem>) {
    if (items.isEmpty()) return
    val currencyDisplay = LocalCurrencyDisplay.current
    val visuals = LocalThemeVisuals.current
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "正式固定支出",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = "${items.count { it.status == "active" }} 活跃",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
            Text(
                text = "这些是已经手动确认过的固定支出；只做提醒和对比，不会自动入账。",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            items.take(5).forEachIndexed { index, item ->
                if (index > 0) {
                    HorizontalDivider(color = visuals.chipUnselected.copy(alpha = 0.72f))
                }
                RecurringItemSummaryRow(item, currencyDisplay)
            }
        }
    }
}

@Composable
private fun RecurringItemSummaryRow(
    item: RecurringItem,
    currencyDisplay: CurrencyDisplay,
) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = item.merchant.ifBlank { "未填写商家" },
                modifier = Modifier
                    .weight(1f)
                    .padding(end = 8.dp),
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = formatDisplayAmount(item.lastAmountCents, currencyDisplay),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.body.weight,
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            RecurringStatusChip(item.status)
            Text(
                text = recurringItemMeta(item),
                modifier = Modifier.weight(1f),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun RecurringCandidateRow(
    candidate: RecurringCandidate,
    currencyDisplay: CurrencyDisplay,
) {
    val visuals = LocalThemeVisuals.current
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = candidate.merchant.ifBlank { "未填写商家" },
                modifier = Modifier
                    .weight(1f)
                    .padding(end = 8.dp),
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = formatDisplayAmount(candidate.amountCents, currencyDisplay),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.body.weight,
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ConfidenceChip(candidate.confidence)
            Text(
                text = "${candidate.occurrenceCount} 次 · ${candidate.reason}",
                modifier = Modifier.weight(1f),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun RecurringStatusChip(status: String) {
    val visuals = LocalThemeVisuals.current
    val (label, bg) = when (status) {
        "active" -> "活跃" to visuals.chipSelected
        "paused" -> "暂停" to visuals.glassTint.copy(alpha = 0.85f)
        else -> status to visuals.chipUnselected.copy(alpha = 0.85f)
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(bg)
            .padding(horizontal = 8.dp, vertical = 2.dp),
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurface,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

@Composable
private fun ConfidenceChip(confidence: String) {
    val visuals = LocalThemeVisuals.current
    val (label, bg) = when (confidence.lowercase()) {
        "high" -> "高" to visuals.chipSelected
        "medium" -> "中" to visuals.glassTint.copy(alpha = 0.85f)
        else -> "低" to visuals.chipUnselected.copy(alpha = 0.85f)
    }
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(bg)
            .padding(horizontal = 8.dp, vertical = 2.dp),
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurface,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

private fun recurringItemMeta(item: RecurringItem): String {
    val next = item.nextExpectedDate?.let { "下次 $it" } ?: "下次未估算"
    val count = "${item.occurrenceCount} 次"
    val anomaly = if (item.anomalyStatus == "higher_than_average") {
        " · 本月偏高 ${item.amountDeltaPercent ?: 0}%"
    } else {
        ""
    }
    return "$next · $count$anomaly"
}
