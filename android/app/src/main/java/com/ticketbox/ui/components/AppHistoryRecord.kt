package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ProvideTextStyle
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.AppSpacing

/** A saved revision stays fully readable, with the event separate from its snapshot. */
@Composable
fun AppHistoryRecord(
    title: String,
    recordedAt: String,
    summary: @Composable ColumnScope.() -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    var expanded by remember(title, recordedAt) { mutableStateOf(false) }
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(recordedAt, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        ProvideTextStyle(MaterialTheme.typography.bodyMedium) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap), content = summary)
            TextButton(onClick = { expanded = !expanded }) {
                Text(stringResource(if (expanded) R.string.plan_history_collapse else R.string.plan_history_expand))
            }
            if (expanded) Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap), content = content)
        }
    }
}

/** Values come from adjacent saved revisions, never the current editor or current ledger currency. */
@Composable
fun AppHistoryComparison(label: String, before: String?, after: String, amount: Boolean = true) {
    Text(label, style = MaterialTheme.typography.titleSmall)
    if (before == null) {
        if (amount) AppAmountText(after) else Text(after, style = MaterialTheme.typography.titleMedium)
    } else {
        AppValueComparison(stringResource(R.string.plan_history_before), before,
            stringResource(R.string.plan_history_after), after) {
            if (amount) AppAmountText(it) else Text(it, style = MaterialTheme.typography.titleMedium)
        }
    }
}

@Composable
fun AppHistoryField(label: String, before: String?, after: String) {
    if (before != null && before != after) AppHistoryComparison(label, before, after, amount = false)
    else Text(stringResource(R.string.plan_history_field, label, after))
}

@Composable
fun AppHistoryScope(versions: List<Long>, hasMore: Boolean, fromCache: Boolean, fetchedAt: String? = null,
    readSourceModifier: Modifier = Modifier) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        if (versions.isNotEmpty()) Text(stringResource(R.string.plan_history_range,
            versions.size, versions.first(), versions.last()), style = MaterialTheme.typography.bodySmall)
        fetchedAt?.let {
            Text(stringResource(if (fromCache) R.string.budget_history_cached else R.string.budget_history_read_at,
                displayDateTime(it)), modifier = readSourceModifier, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (hasMore) Text(stringResource(R.string.plan_history_partial), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
fun AppHistoryBoundary(kind: String, missingPrevious: Boolean) {
    val text = when {
        kind == "baseline" -> R.string.budget_history_baseline_note
        kind != "create" && missingPrevious -> R.string.plan_history_previous_not_loaded
        else -> null
    }
    text?.let { Text(stringResource(it), style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant) }
}

@Composable
fun historyRecordedAmount(amount: Long?, currency: String?): String = when {
    amount == null -> stringResource(R.string.plan_history_amount_unknown)
    currency == null -> stringResource(R.string.budget_history_unknown_money, amount.toString())
    else -> "$currency ${formatDisplayAmount(amount, CurrencyDisplay.forRecord(currency))}"
}
