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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.design.tabularNum

@Composable
internal fun RecurringCandidatesCard(candidates: List<RecurringCandidate>) {
    if (candidates.isEmpty()) return
    val currencyDisplay = LocalCurrencyDisplay.current
    val visuals = LocalThemeVisuals.current
    StatsInsightSurface {
        Column(
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = stringResource(R.string.stats_recurring_candidates_title),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = stringResource(R.string.stats_recurring_candidates_count, candidates.size),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
            Text(
                text = stringResource(R.string.stats_recurring_candidates_subtitle),
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
    StatsInsightSurface {
        Column(
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = stringResource(R.string.stats_recurring_items_title),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = stringResource(R.string.stats_recurring_items_active_count, items.count { it.status == "active" }),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelMedium,
                )
            }
            Text(
                text = stringResource(R.string.stats_recurring_items_subtitle),
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
    val merchantFallback = stringResource(R.string.stats_recurring_merchant_fallback)
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = item.merchant.ifBlank { merchantFallback },
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
                style = MaterialTheme.typography.titleSmall.tabularNum(),
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
    val merchantFallback = stringResource(R.string.stats_recurring_merchant_fallback)
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = candidate.merchant.ifBlank { merchantFallback },
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
                style = MaterialTheme.typography.titleSmall.tabularNum(),
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
                text = stringResource(R.string.stats_recurring_candidate_meta, candidate.occurrenceCount, candidate.reason),
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
        "active" -> stringResource(R.string.recurring_status_active) to visuals.chipSelected
        "paused" -> stringResource(R.string.recurring_status_paused) to visuals.glassTint.copy(alpha = 0.85f)
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
        "high" -> stringResource(R.string.recurring_confidence_high) to visuals.chipSelected
        "medium" -> stringResource(R.string.recurring_confidence_medium) to visuals.glassTint.copy(alpha = 0.85f)
        else -> stringResource(R.string.recurring_confidence_low) to visuals.chipUnselected.copy(alpha = 0.85f)
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
private fun recurringItemMeta(item: RecurringItem): String {
    val next = item.nextExpectedDate?.let { stringResource(R.string.recurring_meta_next, it) }
        ?: stringResource(R.string.recurring_meta_next_unknown)
    val count = stringResource(R.string.recurring_meta_count, item.occurrenceCount)
    val anomaly = if (item.anomalyStatus == "higher_than_average") {
        stringResource(R.string.recurring_meta_anomaly_higher_percent, item.amountDeltaPercent ?: 0)
    } else {
        ""
    }
    return stringResource(R.string.recurring_meta_combined, next, count, anomaly)
}
