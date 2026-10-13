package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.recordCurrencyDisplay
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.expenseSourceLabelRes
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.ExpenseFactUiState

/** Labels only: original facts and server net keep their own currencies; no client arithmetic. */
internal data class FactAmountLabels(
    val original: String,
    val currencyCode: String,
    val homeGross: String?,
    val refunded: String?,
    val net: String?,
)

internal fun factAmountLabels(expense: Expense, bundle: ExpenseFactBundle?): FactAmountLabels {
    val summary = bundle?.takeIf { it.matchesRoot(expense) }?.financialSummary
    val originalCode = expense.originalCurrencyCodeRaw ?: expense.originalCurrencyCode.storageKey
    val homeCode = expense.homeCurrencyCode ?: expense.homeCurrency.storageKey
    val original = summary?.grossOriginalMinor ?: expense.originalAmountMinor
    val display = if (original != null) CurrencyDisplay.forRecord(originalCode) else expense.recordCurrencyDisplay()
    return FactAmountLabels(
        original = formatDisplayAmount(original ?: expense.amountCents, display),
        currencyCode = if (original != null) originalCode else homeCode,
        homeGross = if (original != null && originalCode != homeCode)
            formatDisplayAmount(summary?.grossHomeAmountCents ?: expense.amountCents, expense.recordCurrencyDisplay()) else null,
        refunded = summary?.let { formatDisplayAmount(it.activeRefundedOriginalMinor, CurrencyDisplay.forRecord(originalCode)) },
        net = summary?.let { formatDisplayAmount(it.lineageHomeNetCents, expense.recordCurrencyDisplay()) },
    )
}

@Composable
internal fun FactSummarySection(expense: Expense, state: ExpenseFactUiState, onRetryBundle: () -> Unit) {
    val bundle = state.factBundle?.takeIf { it.matchesRoot(expense) }
    val amounts = factAmountLabels(expense, bundle)
    val status = when (bundle?.financialSummary?.status) {
            ExpenseLineageStatus.PartiallyRefunded -> R.string.ledger_lineage_partially_refunded
            ExpenseLineageStatus.FullyRefunded -> R.string.ledger_lineage_fully_refunded
            ExpenseLineageStatus.Reversed -> R.string.ledger_lineage_reversed
            else -> null
        }
    status?.let { StatusPill(text = stringResource(it), active = false) }
    AppPaperCard {
        Column(Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(stringResource(R.string.expense_fact_original_spend),
                color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
            AppAmountText(amounts.original, role = AppAmountRole.Hero)
            Text(amounts.currencyCode, style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            amounts.homeGross?.let { Text(stringResource(R.string.expense_fact_home_gross, it),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
    }
    FactOffsetSummary(amounts)
    FactOffsetReadStatus(state, onRetryBundle)
}

/** 只保留 hero/meta 未覆盖的事实字段；空值可选字段直接省略（缺备注不是事件）。 */
@Composable
internal fun FactFieldRows(expense: Expense) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        val source = expenseSourceLabelRes(expense.source)?.let { stringResource(it) } ?: expense.source
        if (source.isNotBlank()) Text(stringResource(R.string.expense_edit_source_label, source),
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        expense.tags?.takeIf { it.isNotBlank() }?.let {
            FactFieldRow(label = stringResource(R.string.expense_fact_field_tags), value = it)
        }
        expense.note?.takeIf { it.isNotBlank() }?.let {
            FactFieldRow(label = stringResource(R.string.expense_fact_field_note), value = it)
        }
        com.ticketbox.ui.components.expenseKnownInstant(expense)?.let {
            FactFieldRow(label = stringResource(R.string.calendar_known_instant), value = displayDateTime(it))
        }
        if (expense.accountingTime?.basis?.startsWith("legacy") == true) {
            FactFieldRow(label = stringResource(R.string.calendar_date_basis), value = stringResource(R.string.calendar_legacy_basis_explanation))
        }
        FactScoreFieldRow(expense = expense)
        FactFieldRow(
            label = stringResource(R.string.expense_fact_field_created),
            value = displayDateTime(expense.createdAt),
        )
        expense.confirmedAt?.takeIf { it.isNotBlank() }?.let { confirmedAt ->
            FactFieldRow(
                label = stringResource(R.string.expense_fact_field_confirmed_at),
                value = displayDateTime(confirmedAt),
            )
        }
    }
}

@Composable
private fun FactFieldRow(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.fillMaxWidth(0.3f),
        )
        Text(
            text = value,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

@Composable
private fun FactScoreFieldRow(expense: Expense) {
    if (expense.valueScore == null && expense.regretScore == null) return
    val empty = stringResource(R.string.expense_fact_value_empty)
    FactFieldRow(
        label = stringResource(R.string.expense_fact_field_score),
        value = stringResource(
            R.string.expense_fact_score_pair,
            expense.valueScore?.let { stringResource(R.string.expense_fact_score_format, it) } ?: empty,
            expense.regretScore?.let { stringResource(R.string.expense_fact_score_format, it) } ?: empty,
        ),
    )
}
