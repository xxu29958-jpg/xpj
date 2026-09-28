package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.IncomeRevision
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.IncomeHistoryState

@Composable
internal fun IncomeHistorySheet(state: IncomeHistoryState, onRetry: () -> Unit, onMore: () -> Unit, onDismiss: () -> Unit) {
    AppBusyGuardedSheet(isSubmitting = false, onDismiss = onDismiss, skipPartiallyExpanded = true) {
        AppSheetScaffold(title = stringResource(R.string.income_history_title)) {
            Text(stringResource(R.string.income_history_explanation))
            state.items.forEach { IncomeHistoryEntry(it) }
            if (state.loading) Text(stringResource(R.string.budget_history_loading))
            state.error?.let {
                Text(it.asString())
                TextButton(onClick = onRetry) { Text(stringResource(R.string.common_retry)) }
            }
            if (!state.loading && state.error == null && state.items.isEmpty()) Text(stringResource(R.string.income_history_empty))
            if (state.error == null && state.nextBeforeVersion != null) {
                TextButton(onClick = onMore, enabled = !state.loading) { Text(stringResource(R.string.budget_history_more)) }
            }
        }
    }
}

@Composable
private fun IncomeHistoryEntry(entry: IncomeRevision) {
    val saved = entry.snapshot
    val kind = when (entry.changeKind) {
        "baseline" -> R.string.budget_history_baseline
        "create" -> R.string.income_history_create
        "edit" -> R.string.income_history_edit
        "archive" -> R.string.income_history_archive
        "restore" -> R.string.income_history_restore
        else -> R.string.income_history_title
    }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        HorizontalDivider()
        Text(saved.label, style = MaterialTheme.typography.titleMedium)
        Text(stringResource(R.string.goal_history_version, entry.rowVersion, stringResource(kind)), style = MaterialTheme.typography.bodySmall)
        Text(stringResource(R.string.goal_history_recorded_at, displayDateTime(entry.recordedAt)), style = MaterialTheme.typography.bodySmall)
        if (entry.changeKind == "baseline") Text(stringResource(R.string.budget_history_baseline_note))
        val source = IncomeSourceType.entries.firstOrNull { it.wireValue == saved.sourceType }
        Text(source?.let { stringResource(incomeSourceTypeLabelRes(it)) } ?: saved.sourceType)
        Text(if (saved.homeCurrencyCode == null) stringResource(R.string.budget_history_unknown_money, saved.amountCents.toString())
            else formatDisplayAmount(saved.amountCents, CurrencyDisplay.forRecord(saved.homeCurrencyCode)))
        Text(if (saved.frequency == "one_time") stringResource(R.string.income_history_one_time,
            displayMonthLabel(saved.incomeMonth.orEmpty()), saved.payDay) else stringResource(R.string.income_history_monthly, saved.payDay))
        Text(stringResource(R.string.income_history_months, entry.intentMonth?.let { displayMonthLabel(it) } ?: stringResource(R.string.income_history_unknown),
            entry.effectiveMonth?.let { displayMonthLabel(it) } ?: stringResource(R.string.income_history_unknown)))
        Text(stringResource(if (saved.status == "archived") R.string.income_plan_section_archived else R.string.income_plan_section_active))
    }
}
