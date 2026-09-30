package com.ticketbox.ui.screens.expense.correction

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.FactCorrectionReview

@Composable
internal fun CorrectionReviewPanel(review: FactCorrectionReview, state: ExpenseFactUiState,
    adopt: (Boolean?, Boolean?) -> Unit, refresh: () -> Unit) {
    var keepItems by remember(review) { mutableStateOf<Boolean?>(null) }
    var keepSplits by remember(review) { mutableStateOf<Boolean?>(null) }
    AppSectionHeader(title = stringResource(R.string.expense_correction_review_title))
    val current = review.current
    Text(stringResource(R.string.expense_correction_review_versions, review.original.rowVersion, current.rowVersion),
        style = MaterialTheme.typography.bodySmall)
    CurrentFactEcho(current)
    Text(stringResource(R.string.expense_correction_review_explainer), style = MaterialTheme.typography.bodySmall)
    if (review.itemsChoiceRequired) {
        val currentRows = state.expenseItems?.items.orEmpty().joinToString("\n") { "${it.name} · ${it.kind} · ${homeAmount(it.amountCents, current)}" }
        val originalRows = state.correction.itemDrafts.joinToString("\n") { "${it.name} · ${it.kind} · ${it.amountText}" }
        CollectionReviewChoice(stringResource(R.string.expense_correction_items_entry), currentRows, originalRows, keepItems) { keepItems = it }
    }
    if (review.splitsChoiceRequired) {
        val currentRows = state.expenseSplits?.splits.orEmpty().joinToString("\n") { "${it.accountName} · ${homeAmount(it.amountCents, current)} · ${it.note.orEmpty()}" }
        val originalRows = state.correction.splitDrafts.filter { it.included }.joinToString("\n") { "${it.displayName} · ${it.amountText}" }
        CollectionReviewChoice(stringResource(R.string.expense_correction_splits_entry), currentRows, originalRows, keepSplits) { keepSplits = it }
    }
    TextButton(onClick = { adopt(keepItems, keepSplits) }, enabled = review.ready &&
        (!review.itemsChoiceRequired || keepItems != null) && (!review.splitsChoiceRequired || keepSplits != null)) {
        Text(stringResource(R.string.expense_correction_review_adopt))
    }
    TextButton(onClick = refresh, enabled = !state.expenseLoading && !state.itemsLoading && !state.splitsLoading) {
        Text(stringResource(R.string.expense_fact_refresh_current))
    }
}

@Composable
private fun CurrentFactEcho(current: com.ticketbox.domain.model.Expense) {
    Text(listOfNotNull(current.merchant, current.category,
        formatDisplayAmount(current.originalAmountMinor ?: current.amountCents,
            CurrencyDisplay.forRecord(current.originalCurrencyCodeRaw ?: current.originalCurrencyCode.storageKey)),
        current.accountingTime?.accountingDate ?: current.expenseTime, current.tags, current.note,
        stringResource(R.string.expense_correction_review_scores, current.valueScore?.toString() ?: "—", current.regretScore?.toString() ?: "—"))
        .filter { it.isNotBlank() }.joinToString(" · "), style = MaterialTheme.typography.bodyMedium)
}

private fun homeAmount(amount: Long?, expense: com.ticketbox.domain.model.Expense): String =
    formatDisplayAmount(amount, CurrencyDisplay.forRecord(expense.homeCurrencyCode ?: expense.homeCurrency.storageKey))

@Composable
private fun CollectionReviewChoice(title: String, current: String, original: String, keep: Boolean?, choose: (Boolean) -> Unit) {
    Column {
        Text(title, style = MaterialTheme.typography.titleSmall)
        Text(stringResource(R.string.expense_correction_review_current_rows, current.ifBlank { "—" }), style = MaterialTheme.typography.bodySmall)
        Text(stringResource(R.string.expense_correction_review_original_rows, original.ifBlank { "—" }), style = MaterialTheme.typography.bodySmall)
        FilterChip(selected = keep == true, onClick = { choose(true) }, label = { Text(stringResource(R.string.expense_correction_review_keep_rows)) })
        FilterChip(selected = keep == false, onClick = { choose(false) }, label = { Text(stringResource(R.string.expense_correction_review_use_current)) })
    }
}
